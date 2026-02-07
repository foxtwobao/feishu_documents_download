"""CLI OAuth authentication and token management."""

from __future__ import annotations

__all__ = [
    "CLITokenManager",
    "CLIOAuthClient",
    "TokenCache",
]

import json
import logging
import secrets
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
import shutil
import subprocess
import sys
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

from .config import AuthSettings

logger = logging.getLogger(__name__)


def _copy_to_clipboard(text: str) -> bool:
    """Attempt to copy text to clipboard; return True on success."""

    try:
        import pyperclip  # type: ignore[import]
    except Exception:  # pragma: no cover - optional dependency missing
        pyperclip = None  # type: ignore[assignment]

    if pyperclip is not None:
        try:
            pyperclip.copy(text)  # type: ignore[union-attr]
            return True
        except Exception:  # pragma: no cover - pyperclip backend failure
            pass

    try:
        if sys.platform == "darwin":
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return proc.returncode == 0
        if sys.platform.startswith("win"):
            proc = subprocess.run(
                ["clip"],
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=True,
            )
            return proc.returncode == 0
        for command in (["xclip", "-selection", "clipboard"], ["xsel", "-b"]):
            if shutil.which(command[0]):
                proc = subprocess.run(
                    command,
                    input=text.encode("utf-8"),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if proc.returncode == 0:
                    return True
    except Exception:  # pragma: no cover - clipboard command failure
        return False
    return False


class TokenCache:
    """管理 CLI 模式下的 token 缓存"""

    def __init__(self, cache_path: Optional[Path] = None):
        if cache_path is None:
            cache_dir = Path.home() / ".larksync"
            cache_dir.mkdir(exist_ok=True)
            cache_path = cache_dir / "token_cache.json"
        self.cache_path = cache_path

    def load(self) -> Optional[dict]:
        """从缓存加载 token 数据"""
        if not self.cache_path.exists():
            return None

        try:
            data = json.loads(self.cache_path.read_text())
            # 验证必需字段
            if "access_token" in data and "refresh_token" in data:
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load token cache: {e}")

        return None

    def save(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        """保存 token 到缓存"""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self.cache_path.write_text(json.dumps(data, indent=2))
            logger.info(f"Token saved to {self.cache_path}")
        except OSError as e:
            logger.error(f"Failed to save token cache: {e}")

    def clear(self) -> None:
        """清除缓存"""
        if self.cache_path.exists():
            self.cache_path.unlink()
            logger.info("Token cache cleared")


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """处理 OAuth 回调的 HTTP 请求"""

    authorization_code: Optional[str] = None
    error_message: Optional[str] = None

    def do_GET(self):
        """处理 GET 请求"""
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)

        if "code" in query_params:
            OAuthCallbackHandler.authorization_code = query_params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            success_html = """
            <!DOCTYPE html>
            <html>
            <head><title>授权成功</title></head>
            <body>
                <h1>✅ 授权成功！</h1>
                <p>您已成功完成飞书授权，现在可以关闭此页面并返回终端继续操作。</p>
            </body>
            </html>
            """
            self.wfile.write(success_html.encode())
        elif "error" in query_params:
            OAuthCallbackHandler.error_message = query_params.get("error_description", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            error_html = f"""
            <!DOCTYPE html>
            <html>
            <head><title>授权失败</title></head>
            <body>
                <h1>❌ 授权失败</h1>
                <p>错误信息: {OAuthCallbackHandler.error_message}</p>
            </body>
            </html>
            """
            self.wfile.write(error_html.encode())
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bad Request")

    def log_message(self, format, *args):
        """禁用默认的访问日志"""
        pass


class CLIOAuthClient:
    """命令行模式的 OAuth 客户端"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        callback_url: Optional[str] = None,
        listen_port: int = 8899,
    ):
        self.app_id = app_id
        self.app_secret = app_secret

        # 回调URL用于飞书重定向（可能是反代地址）
        if callback_url:
            self.callback_url = callback_url
        else:
            self.callback_url = f"http://localhost:{listen_port}/callback"

        # 本地监听固定使用 0.0.0.0，端口由 listen_port 指定
        self.callback_host = "0.0.0.0"
        self.callback_port = listen_port

        self.token_cache = TokenCache()

    def build_authorization_url(self, state: str) -> str:
        """构建授权 URL"""
        from urllib.parse import quote_plus

        callback = quote_plus(self.callback_url)
        return (
            "https://passport.feishu.cn/suite/passport/oauth/authorize?"
            f"client_id={self.app_id}&redirect_uri={callback}&response_type=code&state={state}"
        )

    def start_callback_server(self) -> HTTPServer:
        """启动本地回调服务器"""
        if self.callback_host is None or self.callback_port is None:
            raise RuntimeError("Callback host/port not configured for local server.")
        # 使用配置的主机地址，支持内网 IP
        server = HTTPServer((self.callback_host, self.callback_port), OAuthCallbackHandler)
        logger.info(f"Callback server started on {self.callback_host}:{self.callback_port}")
        return server

    def authorize_interactive(self) -> tuple[str, str, int]:
        """
        交互式授权流程：
        1. 打开浏览器跳转到飞书授权页面
        2. 启动本地服务器接收回调
        3. 获取授权码并换取 token
        """
        # 生成 state 用于防止 CSRF 攻击
        state = secrets.token_urlsafe(32)

        # 构建授权 URL
        auth_url = self.build_authorization_url(state)

        # 启动本地回调服务器
        server = self.start_callback_server()
        server_thread = Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        print(f"\n🔐 正在打开浏览器进行飞书授权...")
        print(f"授权 URL: {auth_url}")
        print(f"回调地址: {self.callback_url}")
        if _copy_to_clipboard(auth_url):
            print("📋 授权链接已复制到剪贴板，可直接粘贴到浏览器。")
        else:
            print("⚠️ 无法自动复制，请手动复制上述链接。")
        print("如果浏览器未自动打开，请手动复制上述链接到浏览器中\n")

        # 打开浏览器
        try:
            webbrowser.open(auth_url)
        except Exception as e:
            logger.warning(f"Failed to open browser: {e}")

        print("⏳ 等待授权完成...")

        # 等待回调
        server_thread.join(timeout=120)  # 最多等待2分钟
        server.server_close()

        # 检查是否收到授权码
        if OAuthCallbackHandler.authorization_code is None:
            if OAuthCallbackHandler.error_message:
                raise RuntimeError(f"授权失败: {OAuthCallbackHandler.error_message}")
            raise RuntimeError("授权超时或被取消")

        authorization_code = OAuthCallbackHandler.authorization_code
        OAuthCallbackHandler.authorization_code = None  # 清理

        print("✅ 授权码已获取，正在换取访问令牌...")

        # 换取 token
        access_token, refresh_token, expires_in = self.exchange_code(authorization_code)

        # 保存到缓存
        self.token_cache.save(access_token, refresh_token, expires_in)

        print(f"✅ 访问令牌获取成功！(有效期: {expires_in}秒)\n")

        return access_token, refresh_token, expires_in

    def exchange_code(self, code: str) -> tuple[str, str, int]:
        """使用授权码换取访问令牌"""
        url = "https://passport.feishu.cn/suite/passport/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "code": code,
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()

            if body.get("code") not in (0, None):
                raise RuntimeError(f"Token exchange failed: {body}")

            data = body.get("data") or body
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            expires_in = int(data.get("expires_in", 7200))

            return access_token, refresh_token, expires_in

    def refresh_token(self, refresh_token: str) -> tuple[str, str, int]:
        """使用 refresh token 刷新访问令牌"""
        url = "https://passport.feishu.cn/suite/passport/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "refresh_token": refresh_token,
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()

            if body.get("code") not in (0, None):
                error_msg = body.get("msg", "Unknown error")
                raise RuntimeError(f"Token refresh failed: {error_msg}")

            data = body.get("data") or body
            new_access_token = data["access_token"]
            new_refresh_token = data["refresh_token"]
            expires_in = int(data.get("expires_in", 7200))

            return new_access_token, new_refresh_token, expires_in


class CLITokenManager:
    """CLI 模式的 token 管理器"""

    def __init__(
        self,
        auth_settings: AuthSettings,
        refresh_margin_minutes: int = 10,
    ):
        self.auth_settings = auth_settings
        self.refresh_margin_minutes = refresh_margin_minutes
        self.token_cache = TokenCache()
        self.oauth_client: Optional[CLIOAuthClient] = None

        # 如果配置了 app_id 和 app_secret，初始化 OAuth 客户端
        if auth_settings.app_id and auth_settings.app_secret:
            self.oauth_client = CLIOAuthClient(
                auth_settings.app_id,
                auth_settings.app_secret,
                callback_url=auth_settings.oauth_callback_url,
                listen_port=auth_settings.cli_oauth_listen_port,
            )

    def get_valid_token(self) -> str:
        """
        获取有效的访问令牌，如果需要会自动刷新
        
        优先级：
        1. 配置文件中的 user_access_token（如果存在且不检查过期）
        2. 缓存中的 token（检查过期并自动刷新）
        3. 交互式授权获取新 token
        """
        # 优先使用配置中的 user_access_token（向后兼容）
        if self.auth_settings.user_access_token:
            logger.info("Using user_access_token from configuration")
            return self.auth_settings.user_access_token

        if not self.oauth_client:
            raise RuntimeError(
                "No valid token found and OAuth is not configured. "
                "Please either:\n"
                "1. Set user_access_token in config.toml, or\n"
                "2. Set app_id and app_secret for OAuth authorization"
            )

        # 尝试从缓存加载
        cached = self.token_cache.load()
        if cached:
            # 检查是否需要刷新
            if self._should_refresh(cached):
                logger.info("Token is about to expire, refreshing...")
                try:
                    new_access_token, new_refresh_token, expires_in = self._refresh_cached_token(cached)
                    return new_access_token
                except Exception as e:
                    logger.warning(f"Failed to refresh token: {e}")
                    # 刷新失败，尝试重新授权
                    return self._authorize_and_get_token()
            else:
                logger.info("Using valid token from cache")
                return cached["access_token"]

        # 缓存中没有 token，需要进行授权
        return self._authorize_and_get_token()

    def _should_refresh(self, cached_token: dict) -> bool:
        """检查 token 是否应该刷新"""
        if "expires_at" not in cached_token:
            return False

        try:
            expires_at = datetime.fromisoformat(cached_token["expires_at"])
            margin = timedelta(minutes=self.refresh_margin_minutes)
            return datetime.now(timezone.utc) + margin >= expires_at
        except (ValueError, TypeError):
            return False

    def _refresh_cached_token(self, cached_token: dict) -> tuple[str, str, int]:
        """刷新缓存的 token"""
        if not self.oauth_client:
            raise RuntimeError("OAuth client not configured. Please set app_id and app_secret in config.")

        refresh_token = cached_token["refresh_token"]
        access_token, new_refresh_token, expires_in = self.oauth_client.refresh_token(refresh_token)

        # 更新缓存
        self.token_cache.save(access_token, new_refresh_token, expires_in)
        logger.info("Token refreshed successfully")

        return access_token, new_refresh_token, expires_in

    def _authorize_and_get_token(self) -> str:
        """执行完整的授权流程"""
        if not self.oauth_client:
            raise RuntimeError(
                "No valid token found and OAuth is not configured. "
                "Please either:\n"
                "1. Set user_access_token in config.toml, or\n"
                "2. Set app_id and app_secret for OAuth authorization"
            )

        print("\n" + "=" * 60)
        print("需要进行飞书授权")
        print("=" * 60)

        access_token, _, _ = self.oauth_client.authorize_interactive()
        return access_token

    def clear_cache(self) -> None:
        """清除 token 缓存"""
        self.token_cache.clear()

    def get_token_status(self) -> dict:
        """获取当前 token 状态信息"""
        cached = self.token_cache.load()
        if not cached:
            return {
                "status": "no_cache",
                "message": "没有缓存的 token",
            }

        try:
            expires_at = datetime.fromisoformat(cached["expires_at"])
            now = datetime.now(timezone.utc)
            time_left = expires_at - now

            if time_left.total_seconds() <= 0:
                status = "expired"
                message = "Token 已过期"
            elif time_left.total_seconds() < self.refresh_margin_minutes * 60:
                status = "expiring_soon"
                message = f"Token 即将过期 (剩余 {int(time_left.total_seconds() / 60)} 分钟)"
            else:
                status = "valid"
                message = f"Token 有效 (剩余 {int(time_left.total_seconds() / 3600)} 小时)"

            return {
                "status": status,
                "message": message,
                "expires_at": cached["expires_at"],
                "updated_at": cached.get("updated_at"),
            }
        except (ValueError, TypeError, KeyError):
            return {
                "status": "invalid_cache",
                "message": "缓存数据格式无效",
            }
