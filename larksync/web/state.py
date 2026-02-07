"""Application state management for LarkSync Web."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CLIOAuthSession:
    """Represents a CLI OAuth session."""

    session_id: str
    state: str
    created_at: float = field(default_factory=time.time)
    
    # Set after callback
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    refresh_token_expires_in: Optional[int] = None
    error: Optional[str] = None

    @property
    def status(self) -> str:
        """Get session status."""
        if self.error:
            return "error"
        if self.access_token:
            return "authorized"
        return "pending"


class CLIOAuthSessionStore:
    """
    In-memory store for CLI OAuth sessions.
    
    Used for the shared CLI OAuth callback flow where:
    1. CLI creates a session and opens browser
    2. User authorizes in browser
    3. Browser redirects to callback with code
    4. Server exchanges code for tokens
    5. CLI polls for session status and retrieves tokens
    """

    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize the session store.
        
        Args:
            ttl_seconds: Session time-to-live in seconds (default 5 minutes)
        """
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, CLIOAuthSession] = {}
        self._state_to_session: Dict[str, str] = {}
        self._lock = Lock()

    def create_session(self, session_id: str, state: str) -> CLIOAuthSession:
        """
        Create a new OAuth session.
        
        Args:
            session_id: Unique session identifier
            state: OAuth state parameter
            
        Returns:
            Created session
        """
        session = CLIOAuthSession(session_id=session_id, state=state)
        
        with self._lock:
            self._sessions[session_id] = session
            self._state_to_session[state] = session_id
        
        logger.debug(f"Created CLI OAuth session {session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[CLIOAuthSession]:
        """
        Get a session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session or None if not found/expired
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session and self._is_expired(session):
                self._remove_session(session_id)
                return None
            return session

    def get_session_by_state(self, state: str) -> Optional[CLIOAuthSession]:
        """
        Get a session by OAuth state parameter.
        
        Args:
            state: OAuth state parameter
            
        Returns:
            Session or None if not found/expired
        """
        with self._lock:
            session_id = self._state_to_session.get(state)
            if not session_id:
                return None
            session = self._sessions.get(session_id)
            if session and self._is_expired(session):
                self._remove_session(session_id)
                return None
            return session

    def update_session(
        self,
        session_id: str,
        *,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
        refresh_token_expires_in: Optional[int] = None,
        error: Optional[str] = None,
    ) -> Optional[CLIOAuthSession]:
        """
        Update session with token information.
        
        Args:
            session_id: Session identifier
            access_token: Access token
            refresh_token: Refresh token
            expires_in: Token expiry in seconds
            refresh_token_expires_in: Refresh token expiry in seconds
            error: Error message if authorization failed
            
        Returns:
            Updated session or None if not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            
            if access_token is not None:
                session.access_token = access_token
            if refresh_token is not None:
                session.refresh_token = refresh_token
            if expires_in is not None:
                session.expires_in = expires_in
            if refresh_token_expires_in is not None:
                session.refresh_token_expires_in = refresh_token_expires_in
            if error is not None:
                session.error = error
            
            return session

    def remove_session(self, session_id: str) -> None:
        """Remove a session."""
        with self._lock:
            self._remove_session(session_id)

    def _remove_session(self, session_id: str) -> None:
        """Internal method to remove a session (must hold lock)."""
        session = self._sessions.pop(session_id, None)
        if session:
            self._state_to_session.pop(session.state, None)

    def _is_expired(self, session: CLIOAuthSession) -> bool:
        """Check if a session is expired."""
        return (time.time() - session.created_at) > self.ttl_seconds

    def cleanup_expired(self) -> int:
        """
        Remove all expired sessions.
        
        Returns:
            Number of sessions removed
        """
        removed = 0
        with self._lock:
            expired = [
                sid for sid, session in self._sessions.items()
                if self._is_expired(session)
            ]
            for session_id in expired:
                self._remove_session(session_id)
                removed += 1
        
        if removed:
            logger.debug(f"Cleaned up {removed} expired CLI OAuth sessions")
        return removed
