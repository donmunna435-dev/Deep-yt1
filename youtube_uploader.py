import os
import pickle
import threading
from datetime import datetime
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from config import Config

class YouTubeUploader:
    def __init__(self):
        self.credentials = None
        self.service = None
        self.upload_status = {}
        
    def get_oauth_url(self, user_id):
        """Generate OAuth URL for user"""
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": Config.YOUTUBE_CLIENT_ID,
                    "client_secret": Config.YOUTUBE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [Config.YOUTUBE_REDIRECT_URI]
                }
            },
            scopes=['https://www.googleapis.com/auth/youtube.upload']
        )
        
        flow.redirect_uri = Config.YOUTUBE_REDIRECT_URI
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # Store state for verification
        self._save_state(user_id, state)
        return authorization_url
    
    def handle_callback(self, user_id, authorization_response):
        """Handle OAuth callback and get credentials"""
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": Config.YOUTUBE_CLIENT_ID,
                    "client_secret": Config.YOUTUBE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [Config.YOUTUBE_REDIRECT_URI]
                }
            },
            scopes=['https://www.googleapis.com/auth/youtube.upload']
        )
        
        flow.redirect_uri = Config.YOUTUBE_REDIRECT_URI
        flow.fetch_token(authorization_response=authorization_response)
        
        # Save credentials
        creds = flow.credentials
        self._save_credentials(user_id, creds)
        return True
    
    def _save_credentials(self, user_id, credentials):
        """Save credentials for user"""
        os.makedirs('tokens', exist_ok=True)
        with open(f'tokens/{user_id}.pickle', 'wb') as token:
            pickle.dump(credentials, token)
    
    def _load_credentials(self, user_id):
        """Load credentials for user"""
        token_file = f'tokens/{user_id}.pickle'
        if not os.path.exists(token_file):
            return None
        
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
            
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._save_credentials(user_id, creds)
            
        return creds
    
    def _save_state(self, user_id, state):
        """Save OAuth state"""
        os.makedirs('states', exist_ok=True)
        with open(f'states/{user_id}.state', 'w') as f:
            f.write(state)
    
    def _load_state(self, user_id):
        """Load OAuth state"""
        state_file = f'states/{user_id}.state'
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return f.read().strip()
        return None
    
    def is_authenticated(self, user_id):
        """Check if user is authenticated"""
        return os.path.exists(f'tokens/{user_id}.pickle')
    
    def upload_video(self, user_id, file_path, title, description="", tags=None, category="22", privacy="private"):
        """Upload video to YouTube"""
        if not self.is_authenticated(user_id):
            raise Exception("User not authenticated")
        
        creds = self._load_credentials(user_id)
        youtube = build('youtube', 'v3', credentials=creds)
        
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags or [],
                'categoryId': category
            },
            'status': {
                'privacyStatus': privacy
            }
        }
        
        # Upload in chunks for large files
        media = MediaFileUpload(
            file_path,
            chunksize=1024*1024,
            resumable=True
        )
        
        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        
        # Start upload in background thread
        upload_thread = threading.Thread(
            target=self._resumable_upload,
            args=(request, user_id, file_path)
        )
        upload_thread.start()
        
        return f"Upload started for {title}"
    
    def _resumable_upload(self, request, user_id, file_path):
        """Handle resumable upload with progress tracking"""
        response = None
        retry = 0
        
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    self.upload_status[user_id] = {
                        'progress': progress,
                        'file': os.path.basename(file_path),
                        'status': 'uploading'
                    }
            except Exception as e:
                if retry > 3:
                    self.upload_status[user_id] = {
                        'progress': 0,
                        'file': os.path.basename(file_path),
                        'status': f'error: {str(e)}'
                    }
                    break
                retry += 1
        
        if response:
            self.upload_status[user_id] = {
                'progress': 100,
                'file': os.path.basename(file_path),
                'status': 'completed',
                'video_id': response.get('id')
            }
        
        # Clean up temp file
        try:
            os.remove(file_path)
        except:
            pass
    
    def get_upload_status(self, user_id):
        """Get current upload status for user"""
        return self.upload_status.get(user_id, {'status': 'no_uploads'})