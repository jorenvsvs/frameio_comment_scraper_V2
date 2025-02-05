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
            st.write(f"Response status code: {e.response.status_code if hasattr(e, 'response') else 'unknown'}")
            st.write(f"Response content: {e.response.content if hasattr(e, 'response') else 'unknown'}")
            return []

    def get_asset_items(self, review_link_id):
        """Get items in a review link"""
        url = f"{self.base_url}/review_links/{review_link_id}/items"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            items = response.json()
            st.write(f"Found {len(items)} items in review link {review_link_id}")
            return items
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching review link items: {str(e)}")
            return []

    def get_all_assets(self, project_id):
        """Get all assets in a project through review links"""
        st.write("Starting to collect all assets...")
        assets = []
        
        # Get review links
        review_links = self.get_review_links(project_id)
        
        # Try to get items from each review link
        for review_link in review_links:
            review_link_id = review_link.get('id')
            review_name = review_link.get('name', 'Unnamed review')
            st.write(f"Checking review link: {review_name}")
            
            items = self.get_asset_items(review_link_id)
            for item in items:
                item_type = item.get('type', '')
                st.write(f"Found item: {item.get('name', 'Unnamed')} (Type: {item_type})")
                
                if item_type in ['file', 'version_stack', 'video', 'image', 'pdf', 'audio', 'review']:
                    st.write(f"Adding asset: {item.get('name', 'Unnamed')}")
                    assets.append(item)
        
        st.write(f"Total assets found: {len(assets)}")
        return assets

    def get_asset_comments(self, asset_id):
        """Fetch all comments for an asset"""
        url = f"{self.base_url}/items/{asset_id}/comments"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            comments = response.json()
            if comments:
                st.write(f"Found {len(comments)} comments for asset {asset_id}")
            return comments
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching comments: {str(e)}")
            return []

    # [Rest of the methods remain the same...]
