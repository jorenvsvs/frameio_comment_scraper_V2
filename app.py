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
    def __init__(self, token, include_old_folders=False):
        self.token = token
        self.include_old_folders = include_old_folders
        self.base_url = "https://api.frame.io/v2"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.request_delay = 0.2      # 200ms between requests (was 500ms)
        self.max_retries = 3          # Keep this the same for reliability
        self.retry_delay = 5          # 5 seconds (better to have longer retry delay but shorter chunk delay)
        self.chunk_size = 50          # Process 50 assets at a time (was 30)
        self.chunk_delay = 1          # 1 second between chunks (was 2)
        self.include_old_folders = include_old_folders

    def get_comment_color(self, comment_index):
        """Generate a consistent color for comments"""
        colors = [
            '#FF6B6B',  # Red
            '#4ECDC4',  # Teal
            '#45B7D1',  # Blue
            '#96CEB4',  # Green
            '#FFAD60',  # Orange
            '#9D94FF',  # Purple
            '#FF9999',  # Pink
            '#88D8B0'   # Mint
        ]
        return colors[comment_index % len(colors)]

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
        
    def should_process_folder(self, folder_name):
        """Determine if a folder should be processed based on settings"""
        if not self.include_old_folders and 'old' in folder_name.lower():
            st.write(f"Skipping folder '{folder_name}' (contains 'old')")
            return False
        return True

    def process_folder(self, folder_id, folder_name=""):
        """Recursively process a folder and its contents"""
        if not self.should_process_folder(folder_name):
            return []

        st.write(f"\n>>> Processing folder: {folder_name} ({folder_id})")
        assets = []
        items = self.get_folder_contents(folder_id)
        
        for item in items:
            item_type = item.get('type', '')
            name = item.get('name', 'Unnamed')
            item_id = item.get('id')
            
            st.write(f"Examining item: {name} ({item_type})")
            
            if item_type == 'folder':
                if self.should_process_folder(name):
                    st.write(f"Found subfolder: {name}")
                    subfolder_assets = self.process_folder(item_id, name)
                    assets.extend(subfolder_assets)
                else:
                    st.write(f"Skipping subfolder: {name}")
            elif item_type in ['file', 'version_stack', 'video', 'image', 'pdf', 'audio', 'review', 'asset']:
                st.write(f"Found asset: {name} ({item_type})")
                assets.append(item)
        
        st.write(f"Found {len(assets)} assets in folder {folder_name}")
        return assets
        
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

    def get_folder_path(self, asset, folders=None):
        """Get the full folder path for an asset"""
        if folders is None:
            folders = {}
        
        parent_id = asset.get('parent_id')
        if not parent_id:
            return "/"  # Root folder
            
        if parent_id not in folders:
            try:
                parent = self.get_item_details(parent_id)
                if parent:
                    folders[parent_id] = parent
                    if parent.get('type') == 'folder':
                        parent_path = self.get_folder_path(parent, folders)
                        return f"{parent_path}/{parent.get('name', 'Unknown Folder')}"
            except Exception as e:
                st.write(f"Error getting folder path: {str(e)}")
                
        return "/"

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
                items = self.make_request(endpoint)
                st.write(f"Found {len(items)} items")
                return items
            except requests.exceptions.RequestException:
                continue
        
        st.error(f"All attempts to get folder contents failed for folder {folder_id}")
        return []

    def get_asset_preview(self, asset_id, asset_details):
        """Get preview/thumbnail URL for an asset"""
        try:
            # Check if there's a thumbnail URL directly in the asset details
            if asset_details:
                # Try all possible thumbnail fields
                for field in ['thumbnails', 'thumbnail_url', 'preview_url', 'cover_url']:
                    if field in asset_details:
                        thumbnails = asset_details.get(field)
                        if isinstance(thumbnails, dict):
                            # Try to get the smallest thumbnail first
                            for size in ['small', 'medium', 'large']:
                                if size in thumbnails:
                                    return thumbnails[size]
                        elif isinstance(thumbnails, list) and thumbnails:
                            return thumbnails[0]
                        elif isinstance(thumbnails, str):
                            return thumbnails

            # Fall back to the preview endpoint
            url = f"{self.base_url}/assets/{asset_id}/preview"
            preview_data = self.make_request(url)
            if preview_data and 'url' in preview_data:
                return preview_data['url']
                
        except Exception as e:
            if not (hasattr(e, 'response') and e.response.status_code == 404):
                st.write(f"Error fetching preview for asset {asset_id}: {str(e)}")
        return None

    def process_comment_annotations(self, comment, comment_color):
        """Process annotations from a comment"""
        annotations = comment.get('annotations', [])
        if not annotations:
            return None
            
        try:
            annotation_data = []
            for annotation in annotations:
                # Get the annotation type and data
                a_type = annotation.get('type')
                if a_type in ['rectangle', 'circle', 'arrow', 'line', 'freehand']:
                    data = {
                        'type': a_type,
                        'timestamp': annotation.get('timestamp', 0),
                        'color': comment_color,
                        'points': annotation.get('points', []),
                        'x': annotation.get('x', 0),
                        'y': annotation.get('y', 0),
                        'width': annotation.get('width', 0),
                        'height': annotation.get('height', 0)
                    }
                    annotation_data.append(data)
            return annotation_data if annotation_data else None
        except Exception as e:
            st.write(f"Error processing annotation: {str(e)}")
            return None

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

    def organize_assets_by_folder(self, assets):
        """Organize assets into a folder structure"""
        folders = {}
        organized_assets = []
        
        # First pass: collect all folder information
        for asset in assets:
            folder_path = self.get_folder_path(asset)
            organized_assets.append({
                'asset': asset,
                'folder_path': folder_path
            })
        
        # Sort by folder path and then by asset name
        organized_assets.sort(key=lambda x: (x['folder_path'], x['asset'].get('name', '')))
        return organized_assets

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
        
    def process_comment_author(self, comment):
        """Extract author name from comment with better debugging"""
        author = comment.get('author', {})
        st.write("Author data:", author)  # Debug line
        
        # Try different possible fields
        name = (author.get('name') or 
                author.get('display_name') or 
                author.get('full_name') or 
                author.get('email', 'Unknown User'))
        return name
        
    def generate_report(self, project_id):
        """Generate an HTML report of all comments"""
        assets = self.get_all_assets(project_id)
        
        # Load previous progress if any
        feedback_data, processed_ids = self.load_progress(project_id)
        
        # Filter out already processed assets and organize them
        assets_to_process = [a for a in assets if a['id'] not in processed_ids]
        organized_assets = self.organize_assets_by_folder(assets_to_process)

        # Process assets in order
        folder_feedback = {}
        
        for organized_asset in organized_assets:
            asset = organized_asset['asset']
            folder_path = organized_asset['folder_path']
            
            if folder_path not in folder_feedback:
                folder_feedback[folder_path] = []

            try:
                comments = self.get_asset_comments(asset['id'])
                if comments:
                    processed_comments = []
                    for comment_idx, comment in enumerate(comments):
                        try:
                            author_name = self.process_comment_author(comment)
                            comment_text = comment.get('text', 'No comment text')
                            created_at = comment.get('created_at', datetime.now().isoformat())
                            
                            comment_color = self.get_comment_color(comment_idx)
                            annotations = self.process_comment_annotations(comment, comment_color)
                            
                            processed_comments.append({
                                'text': comment_text,
                                'author': author_name,
                                'timestamp': datetime.fromisoformat(created_at).strftime('%Y-%m-%d %H:%M'),
                                'timestamp_raw': created_at,
                                'annotations': annotations,
                                'color': comment_color,
                                'has_annotations': bool(annotations)
                            })
                        except Exception as e:
                            st.write(f"Error processing comment: {str(e)}")
                            continue
                    
                    if processed_comments:
                        folder_feedback[folder_path].append({
                            'asset_name': asset.get('name', 'Unnamed Asset'),
                            'asset_type': asset.get('type', 'unknown'),
                            'thumbnail_url': self.get_asset_preview(asset['id'], asset),
                            'asset_url': f"https://app.frame.io/player/{asset['id']}",
                            'comments': processed_comments
                        })

            except Exception as e:
                st.error(f"Error processing asset {asset.get('name', 'Unnamed')}: {str(e)}")
                continue

        return self.render_html_report(folder_feedback)



def process_comment_author(self, comment):
    """Extract author name from comment with better debugging"""
    author = comment.get('author', {})
    st.write("Author data:", author)  # Debug line
    
    # Try different possible fields
    name = (author.get('name') or 
            author.get('display_name') or 
            author.get('full_name') or 
            author.get('email', 'Unknown User'))
    return name

def get_asset_preview(self, asset_id, asset_details):
    """Get preview/thumbnail URL for an asset with better debugging"""
    st.write(f"Asset details for preview: {json.dumps(asset_details, indent=2)}")  # Debug line
    
    try:
        # First try to get the preview URL
        url = f"{self.base_url}/assets/{asset_id}/preview"
        preview_data = self.make_request(url)
        st.write(f"Preview endpoint response: {json.dumps(preview_data, indent=2)}")  # Debug line
        
        if preview_data and isinstance(preview_data, dict):
            if 'url' in preview_data:
                return preview_data['url']
        
        # If no preview, try to get the source URL
        if asset_details:
            for key in ['url', 'source_url', 'original_url', 'download_url']:
                if key in asset_details:
                    return asset_details[key]
        
    except Exception as e:
        st.write(f"Error getting preview: {str(e)}")
    return None

def generate_svg_overlay(self, annotations, image_width=200, image_height=112):
    """Generate SVG overlay for annotations"""
    if not annotations:
        return ""
    
    st.write(f"Generating SVG for annotations: {json.dumps(annotations, indent=2)}")  # Debug line
    
def scale_point(point, dimension):
    """Scale point to percentage"""
    return (point * 100.0) / dimension
    
    svg_paths = []
    for ann in annotations:
        if ann['type'] == 'rectangle':
            x = scale_point(ann['x'], image_width)
            y = scale_point(ann['y'], image_height)
            width = scale_point(ann['width'], image_width)
            height = scale_point(ann['height'], image_height)
            svg_paths.append(
                f'<rect x="{x}%" y="{y}%" width="{width}%" height="{height}%" '
                f'fill="none" stroke="{ann["color"]}" stroke-width="2" />'
            )
        elif ann['type'] == 'arrow':
            if ann['points']:
                start = ann['points'][0]
                end = ann['points'][-1]
                x1 = scale_point(start[0], image_width)
                y1 = scale_point(start[1], image_height)
                x2 = scale_point(end[0], image_width)
                y2 = scale_point(end[1], image_height)
                svg_paths.append(
                    f'<line x1="{x1}%" y1="{y1}%" x2="{x2}%" y2="{y2}%" '
                    f'stroke="{ann["color"]}" stroke-width="2" marker-end="url(#arrow)" />'
                )
        elif ann['type'] == 'freehand':
            if ann['points']:
                points = [(scale_point(p[0], image_width), 
                          scale_point(p[1], image_height)) for p in ann['points']]
                path_d = f'M {points[0][0]},{points[0][1]}'
                for p in points[1:]:
                    path_d += f' L {p[0]},{p[1]}'
                svg_paths.append(
                    f'<path d="{path_d}" fill="none" '
                    f'stroke="{ann["color"]}" stroke-width="2" />'
                )
    
    if svg_paths:
        markers = '''
            <defs>
                <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3"
                    orient="auto" markerUnits="strokeWidth">
                    <path d="M0,0 L0,6 L9,3 z" fill="currentColor"/>
                </marker>
            </defs>
        '''
        return f'''
            <svg class="annotation-overlay" viewBox="0 0 100 100" 
                 preserveAspectRatio="none" 
                 style="position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none;">
                {markers}
                {" ".join(svg_paths)}
            </svg>
        '''
    return ""
    
def render_html_report(self, folder_feedback):
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
            .folder-section {
                margin: 30px 0;
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                overflow: hidden;
            }
            .folder-header {
                padding: 20px;
                background: #f8f9fa;
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;
                border-bottom: 1px solid #eee;
            }
            .folder-header:hover {
                background: #f0f0f0;
            }
            .folder-title {
                font-size: 1.2em;
                color: #333;
                margin: 0;
                flex-grow: 1;
            }
            .folder-content {
                max-height: 0;
                overflow: hidden;
                transition: max-height 0.3s ease-out;
            }
            .folder-content.open {
                max-height: none;
            }
            .folder-toggle {
                margin-right: 10px;
                width: 20px;
                height: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                transition: transform 0.3s ease;
            }
            .folder-toggle.open {
                transform: rotate(90deg);
            }
            .folder-count {
                background: #e9ecef;
                padding: 4px 8px;
                border-radius: 12px;
                font-size: 0.9em;
                color: #666;
                margin-left: 10px;
            }
            .asset { 
                border-bottom: 1px solid #eee;
                padding: 20px;
            }
            .asset:last-child {
                border-bottom: none;
            }
            .asset-header { 
                display: flex; 
                align-items: flex-start; 
                margin-bottom: 15px;
                gap: 20px;
            }
            .thumbnail-container {
                flex-shrink: 0;
                width: 200px;
                height: 112px;
                background: #f0f0f0;
                border-radius: 4px;
                overflow: hidden;
                position: relative;
            }
            .thumbnail-container:hover {
                opacity: 0.9;
            }
            .thumbnail { 
                width: 100%;
                height: 100%;
                object-fit: cover;
                display: block;
            }
            .asset-info { 
                flex-grow: 1;
            }
            .asset-name { 
                font-size: 1.2em; 
                font-weight: bold; 
                margin: 0 0 8px 0;
            }
            .asset-type {
                color: #666;
                font-size: 0.9em;
                margin-bottom: 8px;
            }
            .asset-link { 
                color: #0066cc; 
                text-decoration: none;
                display: inline-block;
                padding: 4px 8px;
                background: #f0f5ff;
                border-radius: 4px;
            }
            .comments { 
                margin-top: 15px;
            }
            .comment { 
                background: #f8f8f8; 
                padding: 12px; 
                margin: 10px 0; 
                border-radius: 6px;
                border-left: 4px solid #ddd;
            }
            .comment.has-annotation {
                background: #ffffff;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .comment-meta { 
                color: #666; 
                font-size: 0.9em; 
                margin-bottom: 8px;
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
            .summary { 
                background: #eef2ff;
                padding: 20px;
                margin-bottom: 30px;
                border-radius: 8px;
                border: 1px solid #dde5ff;
            }
            .thumbnail-container {
                position: relative;
                width: 200px;
                height: 112px;
                background: #f0f0f0;
                border-radius: 4px;
                overflow: hidden;
            }
            
            .thumbnail {
                width: 100%;
                height: 100%;
                object-fit: contain;
                display: block;
            }
            
            .annotation-overlay {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
            }
        </style>
        <script>
            function toggleFolder(folderId) {
                const header = document.querySelector(`#folder-${folderId} .folder-header`);
                const content = document.querySelector(`#folder-${folderId} .folder-content`);
                const toggle = document.querySelector(`#folder-${folderId} .folder-toggle`);
                
                content.classList.toggle('open');
                toggle.classList.toggle('open');
                
                // Save state to localStorage
                const isOpen = content.classList.contains('open');
                localStorage.setItem(`folder-${folderId}`, isOpen);
            }

            // Restore folder states on page load
            window.onload = function() {
                document.querySelectorAll('.folder-section').forEach(folder => {
                    const folderId = folder.id.split('-')[1];
                    const isOpen = localStorage.getItem(`folder-${folderId}`) === 'true';
                    if (isOpen) {
                        folder.querySelector('.folder-content').classList.add('open');
                        folder.querySelector('.folder-toggle').classList.add('open');
                    }
                });
            }
        </script>
    </head>
    <body>
        <h1>Frame.io Feedback Report</h1>
        <div class="summary">
            <p>Total folders with feedback: {{ folder_feedback.keys()|length }}</p>
            <p>Total assets with feedback: {{ folder_feedback.values()|map('length')|sum }}</p>
            <p>Generated: {{ now }}</p>
        </div>
        {% for folder_path, assets in folder_feedback.items()|sort %}
        <div class="folder-section" id="folder-{{ loop.index }}">
            <div class="folder-header" onclick="toggleFolder('{{ loop.index }}')">
                <div class="folder-toggle">▶</div>
                <h2 class="folder-title">{{ folder_path }}</h2>
                <span class="folder-count">{{ assets|length }} asset{% if assets|length != 1 %}s{% endif %}</span>
            </div>
            <div class="folder-content">
                {% for asset in assets %}
                <div class="asset">
                    <div class="asset-header">
                        <a href="{{ asset.asset_url }}" target="_blank" class="thumbnail-container">
                            {% if asset.thumbnail_url %}
                                <img class="thumbnail" src="{{ asset.thumbnail_url }}" alt="{{ asset.asset_name }}">
                            {% else %}
                                <div class="no-thumbnail">No preview available</div>
                            {% endif %}
                        </a>
                        <div class="asset-info">
                            <h2 class="asset-name">{{ asset.asset_name }}</h2>
                            <div class="asset-type">{{ asset.asset_type }}</div>
                            <a href="{{ asset.asset_url }}" class="asset-link" target="_blank">View in Frame.io →</a>
                        </div>
                    </div>
                    <div class="comments">
                        {% for comment in asset.comments %}
                        <div class="comment {% if comment.has_annotations %}has-annotation{% endif %}" 
                             style="border-left-color: {{ comment.color }}; {% if comment.has_annotations %}border-width: 4px;{% endif %}">
                            <div class="comment-meta" style="color: {{ comment.color }};">
                                <strong>{{ comment.author }}</strong> - {{ comment.timestamp }}
                            </div>
                            {% if comment.has_annotations %}
                            <div class="comment-thumbnail">
                               <div class="thumbnail-container">
                                    <a href="{{ asset.asset_url }}" target="_blank">
                                        {% if asset.thumbnail_url %}
                                            <img class="thumbnail" src="{{ asset.thumbnail_url }}" alt="{{ asset.asset_name }}"
                                                 onerror="this.parentElement.innerHTML='<div class=\'no-thumbnail\'>No preview available</div>';">
                                            {% if comment.annotations %}
                                                {{ generate_svg_overlay(comment.annotations)|safe }}
                                            {% endif %}
                                        {% else %}
                                            <div class="no-thumbnail">No preview available</div>
                                        {% endif %}
                                    </a>
                                </div>
                            </div>
                            {% endif %}
                            {{ comment.text }}
                        </div>
                        {% endfor %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endfor %}
    </body>
    </html>
    """
    
    return Template(template_str).render(
        folder_feedback=folder_feedback,
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

def main():
    st.set_page_config(page_title="Frame.io Feedback Exporter", page_icon="📋", layout="wide")
    
    st.title("Frame.io Feedback Exporter")
    st.write("""
    Generate a comprehensive report of all comments from your Frame.io projects.
    You'll need your Frame.io API token to use this tool.
    """)
    
    # Add checkbox for including old folders
    include_old_folders = st.checkbox('Include folders containing "old" in their name', value=False)
    
    # API Token input with secure handling
    api_token = st.text_input(
        "Enter your Frame.io API Token",
        type="password",
        help="Find this in your Frame.io account settings under Developer section"
    )
    
    if api_token:
        try:
            exporter = FrameIOFeedbackExporter(token=api_token, include_old_folders=include_old_folders)
        
            
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
