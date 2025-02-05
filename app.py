import streamlit as st
import requests
from datetime import datetime
import json
import base64
from jinja2 import Template

class FrameIOFeedbackExporter:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://api.frame.io/v2"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def get_teams(self):
        """Fetch all accessible teams"""
        url = f"{self.base_url}/teams"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching teams: {str(e)}")
            return []

    def get_team_projects(self, team_id):
        """Fetch all projects for a team"""
        url = f"{self.base_url}/teams/{team_id}/projects"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching team projects: {str(e)}")
            return []

    def get_review_links(self, project_id):
        """Get review links for a project"""
        url = f"{self.base_url}/projects/{project_id}/review_links"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            review_links = response.json()
            st.write(f"Found {len(review_links)} review links in project")
            return review_links
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching review links: {str(e)}")
            st.write(f"Response status: {e.response.status_code if hasattr(e, 'response') else 'unknown'}")
            st.write(f"Response content: {e.response.content if hasattr(e, 'response') else 'unknown'}")
            return []

    def get_folder_contents(self, folder_id):
        """Get contents of a folder"""
        st.write(f"Getting contents of folder {folder_id}")
        # Try different endpoints to get folder contents
        endpoints = [
            f"{self.base_url}/assets/{folder_id}/children",
            f"{self.base_url}/folders/{folder_id}/items",
            f"{self.base_url}/folders/{folder_id}/children"
        ]
        
        for endpoint in endpoints:
            try:
                st.write(f"Trying endpoint: {endpoint}")
                response = requests.get(endpoint, headers=self.headers)
                response.raise_for_status()
                items = response.json()
                st.write(f"Success! Found {len(items)} items")
                for item in items:
                    st.write(f"Item in folder: {item.get('name', 'Unnamed')} (Type: {item.get('type', 'unknown')})")
                return items
            except requests.exceptions.RequestException as e:
                st.write(f"Endpoint {endpoint} failed: {str(e)}")
                continue
        
        st.error(f"All attempts to get folder contents failed for folder {folder_id}")
        return []

    def process_folder(self, folder_id, folder_name=""):
        """Recursively process a folder and its contents"""
        st.write(f"\n>>> Processing folder: {folder_name} ({folder_id})")
        assets = []
        items = self.get_folder_contents(folder_id)
        
        for item in items:
            item_type = item.get('type', '')
            name = item.get('name', 'Unnamed')
            item_id = item.get('id')
            
            st.write(f"Examining item: {name} ({item_type})")
            
            if item_type == 'folder':
                st.write(f"Found subfolder: {name}")
                subfolder_assets = self.process_folder(item_id, name)
                assets.extend(subfolder_assets)
            elif item_type in ['file', 'version_stack', 'video', 'image', 'pdf', 'audio', 'review', 'asset']:
                st.write(f"Found asset: {name} ({item_type})")
                assets.append(item)
        
        st.write(f"Found {len(assets)} assets in folder {folder_name}")
        return assets

    def get_all_assets(self, project_id):
        """Get all assets in a project through review links"""
        st.write("Starting to collect all assets...")
        all_assets = []
        
        # Get review links
        review_links = self.get_review_links(project_id)
        
        # Process each review link
        for review_link in review_links:
            review_link_id = review_link.get('id')
            review_name = review_link.get('name', 'Unnamed review')
            st.write(f"\nProcessing review link: {review_name}")
            
            # Get items in review link
            url = f"{self.base_url}/review_links/{review_link_id}/items"
            try:
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                items = response.json()
                st.write(f"Found {len(items)} items in review link")
                
                # Process each item
                for item in items:
                    asset_id = item.get('asset_id')
                    if asset_id:
                        st.write(f"\nChecking asset: {asset_id}")
                        # Get asset details
                        asset_details = self.get_item_details(asset_id)
                        if asset_details:
                            if asset_details.get('type') == 'folder':
                                st.write(f"Processing folder: {asset_details.get('name')}")
                                folder_assets = self.process_folder(asset_id, asset_details.get('name'))
                                if folder_assets:
                                    st.write(f"Adding {len(folder_assets)} assets from folder")
                                    all_assets.extend(folder_assets)
                            else:
                                st.write("Adding single asset")
                                all_assets.append(asset_details)
            except requests.exceptions.RequestException as e:
                st.error(f"Error processing review link: {str(e)}")
        
        st.write(f"\nTotal assets found: {len(all_assets)}")
        return all_assets

    def generate_report(self, project_id):
        """Generate an HTML report of all comments"""
        assets = self.get_all_assets(project_id)
        feedback_data = []
        
        # Progress bar for asset processing
        progress_bar = st.progress(0)
        for idx, asset in enumerate(assets):
            comments = self.get_asset_comments(asset['id'])
            if comments:
                feedback_data.append({
                    'asset_name': asset['name'],
                    'asset_type': asset['type'],
                    'thumbnail_url': asset.get('thumbnail_url', ''),
                    'asset_url': f"https://app.frame.io/presentation/{project_id}?item={asset['id']}",
                    'comments': [{
                        'text': comment['text'],
                        'author': comment['author']['name'],
                        'timestamp': datetime.fromisoformat(comment['created_at']).strftime('%Y-%m-%d %H:%M'),
                        'timestamp_raw': comment['created_at']
                    } for comment in comments]
                })
            progress_bar.progress((idx + 1) / len(assets))
        
        # Sort feedback by most recent comment
        feedback_data.sort(key=lambda x: max([c['timestamp_raw'] for c in x['comments']]) if x['comments'] else '', reverse=True)
        
        return self.render_html_report(feedback_data)

    def render_html_report(self, feedback_data):
        """Render the HTML report using a template"""
        template_str = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Frame.io Feedback Report</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .asset { border: 1px solid #ddd; margin: 20px 0; padding: 20px; border-radius: 5px; }
                .asset-header { display: flex; align-items: center; margin-bottom: 15px; }
                .thumbnail { width: 150px; height: 84px; object-fit: cover; margin-right: 20px; }
                .asset-info { flex-grow: 1; }
                .asset-name { font-size: 1.2em; font-weight: bold; margin: 0; }
                .asset-link { color: #0066cc; text-decoration: none; }
                .comments { margin-top: 15px; }
                .comment { background: #f5f5f5; padding: 10px; margin: 10px 0; border-radius: 3px; }
                .comment-meta { color: #666; font-size: 0.9em; margin-bottom: 5px; }
                .summary { background: #eef; padding: 15px; margin-bottom: 20px; border-radius: 5px; }
                @media print {
                    .asset { break-inside: avoid; }
                }
            </style>
        </head>
        <body>
            <h1>Frame.io Feedback Report</h1>
            <div class="summary">
                <p>Total assets with feedback: {{ feedback_data|length }}</p>
                <p>Total comments: {{ feedback_data|map(attribute='comments')|map('length')|sum }}</p>
                <p>Generated: {{ now }}</p>
            </div>
            {% for asset in feedback_data %}
            <div class="asset">
                <div class="asset-header">
                    {% if asset.thumbnail_url %}
                    <img class="thumbnail" src="{{ asset.thumbnail_url }}" alt="{{ asset.asset_name }}">
                    {% endif %}
                    <div class="asset-info">
                        <h2 class="asset-name">{{ asset.asset_name }}</h2>
                        <p><a href="{{ asset.asset_url }}" class="asset-link" target="_blank">View in Frame.io →</a></p>
                    </div>
                </div>
                <div class="comments">
                    {% for comment in asset.comments %}
                    <div class="comment">
                        <div class="comment-meta">
                            <strong>{{ comment.author }}</strong> - {{ comment.timestamp }}
                        </div>
                        {{ comment.text }}
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
        </body>
        </html>
        """
        
        template = Template(template_str)
        return template.render(
            feedback_data=feedback_data,
            now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

def main():
    st.set_page_config(page_title="Frame.io Feedback Exporter", page_icon="📋", layout="wide")
    
    st.title("Frame.io Feedback Exporter")
    st.write("""
    Generate a comprehensive report of all comments from your Frame.io projects.
    You'll need your Frame.io API token to use this tool.
    """)
    
    # API Token input with secure handling
    api_token = st.text_input(
        "Enter your Frame.io API Token",
        type="password",
        help="Find this in your Frame.io account settings under Developer section"
    )
    
    if api_token:
        try:
            exporter = FrameIOFeedbackExporter(api_token)
            
            # Fetch and display teams
            teams = exporter.get_teams()
            if teams:
                team_options = {t['name']: t['id'] for t in teams}
                selected_team = st.selectbox(
                    "Select Team",
                    options=list(team_options.keys())
                )
                
                # Fetch and display projects for selected team
                if selected_team:
                    team_id = team_options[selected_team]
                    projects = exporter.get_team_projects(team_id)
                    if projects:
                        project_options = {p['name']: p['id'] for p in projects}
                        selected_project = st.selectbox(
                            "Select Project",
                            options=list(project_options.keys())
                        )
                        
                        if st.button("Generate Report"):
                            with st.spinner("Generating report... This might take a few minutes for large projects"):
                                project_id = project_options[selected_project]
                                html_content = exporter.generate_report(project_id)
                                
                                # Create download button for HTML
                                b64 = base64.b64encode(html_content.encode()).decode()
                                href = f'<a href="data:text/html;base64,{b64}" download="frameio_feedback_report.html">Download Report</a>'
                                st.markdown(href, unsafe_allow_html=True)
                                
                                # Preview
                                st.write("### Preview:")
                                st.components.v1.html(html_content, height=600, scrolling=True)
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()
