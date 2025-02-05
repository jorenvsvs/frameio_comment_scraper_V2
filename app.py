import streamlit as st
import requests
from datetime import datetime
import json
import base64
from jinja2 import Template
import time
import pickle
import os

class FrameIOFeedbackExporter:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://api.frame.io/v2"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.request_delay = 2.0     # 10 seconds between requests
        self.max_retries = 3
        self.retry_delay = 5         # 1 minute initial retry delay
        self.chunk_size = 20          # Process 10 assets at a time
        self.chunk_delay = 10        # 5 minutes between chunks

    def save_progress(self, project_id, feedback_data, processed_ids):
        """Save current progress to a file"""
        data = {
            'feedback_data': feedback_data,
            'processed_ids': processed_ids,
            'timestamp': datetime.now().isoformat()
        }
        with open(f'frameio_progress_{project_id}.pkl', 'wb') as f:
            pickle.dump(data, f)

    def load_progress(self, project_id):
        """Load previous progress if it exists"""
        try:
            with open(f'frameio_progress_{project_id}.pkl', 'rb') as f:
                data = pickle.load(f)
                st.write("Found previous progress. Resuming...")
                return data['feedback_data'], data['processed_ids']
        except:
            return [], set()

    def make_request(self, url, method='GET'):
        """Make a rate-limited request with retries"""
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.request_delay)
                response = requests.request(method, url, headers=self.headers)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (4 ** attempt)
                    st.write(f"Rate limit hit. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                raise
        return None

    def get_teams(self):
        """Fetch all accessible teams"""
        try:
            return self.make_request(f"{self.base_url}/teams")
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching teams: {str(e)}")
            return []

    def get_team_projects(self, team_id):
        """Fetch all projects for a team"""
        try:
            return self.make_request(f"{self.base_url}/teams/{team_id}/projects")
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching team projects: {str(e)}")
            return []

    def get_review_links(self, project_id):
        """Get review links for a project"""
        try:
            review_links = self.make_request(f"{self.base_url}/projects/{project_id}/review_links")
            st.write(f"Found {len(review_links)} review links in project")
            return review_links
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching review links: {str(e)}")
            return []

    def get_item_details(self, item_id):
        """Get detailed information about an item"""
        try:
            item_details = self.make_request(f"{self.base_url}/assets/{item_id}")
            st.write(f"Got details for item: {item_details.get('name', 'Unnamed')} (Type: {item_details.get('type', 'unknown')})")
            return item_details
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching item details: {str(e)}")
            return None

    def get_folder_contents(self, folder_id):
        """Get contents of a folder"""
        st.write(f"Getting contents of folder {folder_id}")
        endpoints = [
            f"{self.base_url}/assets/{folder_id}/items",
            f"{self.base_url}/assets/{folder_id}/children",
            f"{self.base_url}/folders/{folder_id}/items",
            f"{self.base_url}/folders/{folder_id}/children"
        ]
        
        for endpoint in endpoints:
            try:
                st.write(f"Trying endpoint: {endpoint}")
                items = self.make_request(endpoint)
                st.write(f"Success! Found {len(items)} items")
                return items
            except requests.exceptions.RequestException:
                continue
        
        st.error(f"All attempts to get folder contents failed for folder {folder_id}")
        return []

    def get_asset_preview(self, asset_id, asset_details):
        """Get preview/thumbnail URL for an asset"""
        try:
            # First try to get the preview
            url = f"{self.base_url}/assets/{asset_id}/preview"
            preview_data = self.make_request(url)
            if preview_data and 'url' in preview_data:
                return preview_data['url']
            
            # If no preview, try to use the direct asset URL if available
            if asset_details and 'url' in asset_details:
                return asset_details['url']
                
        except requests.exceptions.RequestException as e:
            if not (hasattr(e, 'response') and e.response.status_code == 404):
                st.write(f"Error fetching preview for asset {asset_id}: {str(e)}")
        return None

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

    def get_asset_comments(self, asset_id):
        """Fetch all comments for an asset"""
        try:
            comments = self.make_request(f"{self.base_url}/assets/{asset_id}/comments")
            if comments:
                st.write(f"Found {len(comments)} comments for asset {asset_id}")
            return comments
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching comments: {str(e)}")
            return []

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
                items = self.make_request(url)
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
        
        # Load previous progress if any
        feedback_data, processed_ids = self.load_progress(project_id)
        
        # Filter out already processed assets
        assets_to_process = [a for a in assets if a['id'] not in processed_ids]
        
        total_assets = len(assets_to_process)
        st.write(f"Processing {total_assets} remaining assets in chunks of {self.chunk_size}")
        
        progress_bar = st.progress(len(processed_ids) / len(assets))
        
        # Process assets in chunks
        for chunk_start in range(0, total_assets, self.chunk_size):
            chunk = assets_to_process[chunk_start:chunk_start + self.chunk_size]
            st.write(f"\nProcessing chunk {chunk_start//self.chunk_size + 1} of {(total_assets + self.chunk_size - 1)//self.chunk_size}")
            
            # Process each asset in the chunk
            for asset in chunk:
                try:
                    comments = self.get_asset_comments(asset['id'])
                    if comments:
                        processed_comments = []
                        for comment in comments:
                            try:
                                # More detailed user information extraction
                                author = comment.get('author', {})
                                author_name = author.get('name')
                                if not author_name:  # Fallback options if name isn't directly available
                                    author_name = author.get('display_name') or author.get('email') or "Unknown User"
                                
                                comment_text = comment.get('text', 'No comment text')
                                created_at = comment.get('created_at', datetime.now().isoformat())
                                
                                processed_comments.append({
                                    'text': comment_text,
                                    'author': author_name,
                                    'timestamp': datetime.fromisoformat(created_at).strftime('%Y-%m-%d %H:%M'),
                                    'timestamp_raw': created_at
                                })
                            except Exception as e:
                                st.write(f"Error processing comment: {str(e)}")
                                continue
                        
                        if processed_comments:
                            # Get preview URL for the asset
                            preview_url = self.get_asset_preview(asset['id'], asset)
                            
                            feedback_data.append({
                                'asset_name': asset.get('name', 'Unnamed Asset'),
                                'asset_type': asset.get('type', 'unknown'),
                                'thumbnail_url': preview_url,
                                'asset_url': f"https://app.frame.io/presentation/{project_id}?item={asset['id']}",
                                'comments': processed_comments
                            })
                    
                    processed_ids.add(asset['id'])
                    # Save progress after each asset
                    self.save_progress(project_id, feedback_data, processed_ids)
                    
                except Exception as e:
                    st.error(f"Error processing asset {asset.get('name', 'Unnamed')}: {str(e)}")
                    continue
                
                progress_bar.progress(len(processed_ids) / len(assets))
            
            # After each chunk, take a long break
            if chunk_start + self.chunk_size < total_assets:
                st.write(f"Chunk complete. Waiting {self.chunk_delay} seconds before next chunk...")
                time.sleep(self.chunk_delay)
        
        if feedback_data:
            feedback_data.sort(
                key=lambda x: max([c['timestamp_raw'] for c in x['comments']], default=''),
                reverse=True
            )
        
        # Clean up progress file
        try:
            os.remove(f'frameio_progress_{project_id}.pkl')
        except:
            pass
        
        return self.render_html_report(feedback_data)

    def render_html_report(self, feedback_data):
        """Render the HTML report using a template"""
        template_str = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Frame.io Feedback Report</title>
            <style>
                body { 
                    font-family: Arial, sans-serif; 
                    margin: 20px;
                    background: #f5f5f5;
                }
                .asset { 
                    border: 1px solid #ddd; 
                    margin: 20px 0; 
                    padding: 20px; 
                    border-radius: 8px;
                    background: white;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .asset-header { 
                    display: flex; 
                    flex-direction: column;
                    margin-bottom: 15px;
                    gap: 20px;
                }
                .thumbnail-container {
                    width: 960px;
                    height: 540px;
                    background: #f0f0f0;
                    border-radius: 4px;
                    overflow: hidden;
                    position: relative;
                    margin: 0 auto;
                }
                .thumbnail { 
                    width: 100%;
                    height: 100%;
                    object-fit: contain;
                    display: block;
                }
                .no-thumbnail {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 100%;
                    height: 100%;
                    color: #999;
                    font-size: 0.9em;
                }
                .asset-info { 
                    flex-grow: 1;
                    min-width: 0;
                }
                .asset-name { 
                    font-size: 1.4em; 
                    font-weight: bold; 
                    margin: 0 0 8px 0;
                    word-break: break-word;
                }
                .asset-type {
                    color: #666;
                    font-size: 0.9em;
                    margin-bottom: 8px;
                    text-transform: capitalize;
                }
                .asset-link { 
                    color: #0066cc; 
                    text-decoration: none;
                    display: inline-block;
                    padding: 8px 16px;
                    background: #f0f5ff;
                    border-radius: 4px;
                    margin-top: 8px;
                }
                .asset-link:hover {
                    background: #e0ebff;
                }
                .comments { 
                    margin-top: 20px;
                }
                .comment { 
                    background: #f8f8f8; 
                    padding: 16px; 
                    margin: 10px 0; 
                    border-radius: 6px;
                    border-left: 4px solid #ddd;
                }
                .comment-meta { 
                    color: #666; 
                    font-size: 0.9em; 
                    margin-bottom: 8px;
                    padding-bottom: 8px;
                    border-bottom: 1px solid #eee;
                }
                .summary { 
                    background: #eef2ff;
                    padding: 20px;
                    margin-bottom: 30px;
                    border-radius: 8px;
                    border: 1px solid #dde5ff;
                }
                .page-title {
                    color: #333;
                    padding: 20px 0;
                    margin: 0;
                    text-align: center;
                    font-size: 2em;
                }
                @media print {
                    .asset { break-inside: avoid; page-break-inside: avoid; }
                    body { background: white; }
                    .asset { box-shadow: none; }
                }
            </style>
        </head>
        <body>
            <h1 class="page-title">Frame.io Feedback Report</h1>
            <div class="summary">
                <p>Total assets with feedback: {{ feedback_data|length }}</p>
                <p>Total comments: {{ feedback_data|map(attribute='comments')|map('length')|sum }}</p>
                <p>Generated: {{ now }}</p>
            </div>
            {% for asset in feedback_data %}
            <div class="asset">
                <div class="asset-header">
                    <div class="asset-info">
                        <h2 class="asset-name">{{ asset.asset_name }}</h2>
                        <div class="asset-type">{{ asset.asset_type }}</div>
                        <a href="{{ asset.asset_url }}" class="asset-link" target="_blank">View in Frame.io →</a>
                    </div>
                    <div class="thumbnail-container">
                        {% if asset.thumbnail_url %}
                            <img class="thumbnail" src="{{ asset.thumbnail_url }}" alt="{{ asset.asset_name }}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
                            <div class="no-thumbnail" style="display: none;">No preview available</div>
                        {% else %}
                            <div class="no-thumbnail">No preview available</div>
                        {% endif %}
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
               
