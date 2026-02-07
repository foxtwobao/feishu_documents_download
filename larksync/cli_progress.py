"""Terminal progress tracker for CLI sync operations."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer


class TerminalProgressTracker:
    """实时追踪同步进度并在终端输出美观的进度信息"""
    
    def __init__(self, limit: Optional[int] = None, sync_type: str = "space") -> None:
        self.downloaded = 0
        self.skipped = 0
        self.failed = 0
        self.total = 0
        self.discovered = 0
        self._pending_due_to_limit = 0
        self.locked_total = 0  # 锁定的总文件数（扫描阶段确定后不再变化）
        self.current_item: Optional[str] = None
        self.current_stage: Optional[str] = None
        self.root_name: Optional[str] = None
        self._last_line_length = 0
        self._total_locked = False  # 标记总数是否已锁定
        self._limit = limit  # 保存limit用于判断锁定时机
        self._phase: str = "idle"
        self._discovery_truncated = False
        self._sync_type = sync_type  # 同步类型: "space" 或 "wiki"
    
    def start(self) -> None:
        """开始同步时的提示"""
        typer.echo()
        if self._sync_type == "wiki":
            typer.secho("🚀 开始同步飞书知识库...", fg=typer.colors.CYAN, bold=True)
        else:
            typer.secho("🚀 开始同步飞书个人空间...", fg=typer.colors.CYAN, bold=True)
        typer.echo("━" * 60)
    
    def show_discovery(self, discovered: int, name: Optional[str] = None) -> None:
        """扫描阶段实时输出已发现的文件数量。"""
        self._phase = "discovery"
        self.discovered = discovered
        self._render(
            processed=discovered,
            expected=max(discovered, 1),
            name=name,
            stage="discover",
            file_type=None,
            detail=None,
        )
    
    def announce_plan(
        self,
        total_found: int,
        to_download: int,
        skipped: int,
        pending_limit: int,
        truncated: bool = False,
    ) -> None:
        """扫描结束后，展示统计并准备下载阶段。"""
        self._flush_line()
        self.discovered = total_found
        self.downloaded = 0
        self.failed = 0
        self.skipped = skipped
        self._pending_due_to_limit = pending_limit
        self.total = to_download
        self._phase = "download" if to_download > 0 else "done"
        self._discovery_truncated = truncated
        
        typer.echo()
        typer.secho(
            f"🔍 已发现 {total_found} 个文件，其中 {to_download} 个需要下载（增量）",
            fg=typer.colors.CYAN,
        )
        if skipped > 0:
            typer.secho(f"  ⏭️  已确认存在: {skipped} 个", fg=typer.colors.YELLOW)
        if pending_limit > 0:
            typer.secho(f"  ⚠️  因 limit 未处理: {pending_limit} 个", fg=typer.colors.RED)
        if truncated:
            typer.secho("  ⚠️  已达到 limit，停止继续扫描，可能仍有更多文件未统计。", fg=typer.colors.YELLOW)
        if to_download > 0:
            typer.echo()
            typer.secho("⬇️  开始下载...", fg=typer.colors.GREEN)
            typer.echo()
        else:
            typer.echo()
            typer.secho("✅ 无需下载，所有文件均为最新。", fg=typer.colors.GREEN)
            typer.echo()
    
    def update(
        self, 
        processed: int, 
        expected: int, 
        name: Optional[str], 
        stage: str, 
        file_type: Optional[str], 
        detail: Optional[str]
    ) -> None:
        """
        更新进度信息
        
        Args:
            processed: 已处理的文件数
            expected: 预期总文件数
            name: 当前文件名
            stage: 当前阶段 (plan/start/success/skip/failed/progress)
            file_type: 文件类型
            detail: 详细信息
        """
        # 锁定策略：下载阶段如果设置了 limit，使用 limit 作为显示的总数
        if stage != "discover" and self._limit is not None:
            display_total = self._limit
        else:
            # 如果没有 limit，就使用 expected（会不断增长）
            display_total = expected
        
        self.total = display_total
        self.current_item = name
        self.current_stage = stage
        
        # 更新统计
        if stage == "success":
            self.downloaded += 1
        elif stage == "skip":
            self.skipped += 1
        elif stage == "failed":
            self.failed += 1
        
        self._phase = "discover" if stage == "discover" else "download"
        self._render(processed, display_total, name, stage, file_type, detail)
    
    def finish(self, storage_root: Path, summary: dict | None = None) -> None:
        """完成同步时的汇总信息"""
        # 确保上一行已完成
        if self._last_line_length > 0:
            sys.stdout.write('\n')
        
        typer.echo()
        typer.echo("━" * 60)
        typer.secho("✨ 同步完成！", fg=typer.colors.GREEN, bold=True)
        typer.echo()
        typer.secho("📊 统计信息:", fg=typer.colors.CYAN, bold=True)
        
        # 下载数量
        if self.downloaded > 0:
            typer.secho(f"  ✅ 下载: {self.downloaded} 个文件", fg=typer.colors.GREEN)
        
        # 跳过数量
        if self.skipped > 0:
            typer.secho(f"  ⏭️  跳过: {self.skipped} 个文件 (增量策略)", fg=typer.colors.YELLOW)
        
        # 失败数量
        if self.failed > 0:
            typer.secho(f"  ❌ 失败: {self.failed} 个文件", fg=typer.colors.RED)
        
        # 文件夹统计（如果有summary）
        total_folders = 0
        if summary and "total_folders" in summary:
            total_folders = summary.get("total_folders", 0)
            if total_folders > 0:
                typer.secho(f"  📂 文件夹: {total_folders} 个", fg=typer.colors.MAGENTA)
        
        # 总计
        total_processed = self.downloaded + self.skipped + self.failed
        if total_folders > 0:
            typer.secho(f"  📁 总计: {total_processed} 个文件 + {total_folders} 个文件夹", fg=typer.colors.BLUE)
        else:
            typer.secho(f"  📁 总计: {total_processed} 个文件", fg=typer.colors.BLUE)
        if self._discovery_truncated:
            typer.secho("  ⚠️  因 limit 提前结束扫描，未统计的文件将在后续运行时处理。", fg=typer.colors.YELLOW)
        
        typer.echo()
        typer.secho(f"💾 保存位置: {storage_root}", fg=typer.colors.CYAN)
        typer.echo()
    
    def _format_progress_line(
        self, 
        processed: int, 
        expected: int, 
        name: Optional[str], 
        stage: str, 
        file_type: Optional[str],
        detail: Optional[str]
    ) -> str:
        """格式化进度行"""
        
        # 进度百分比
        if stage == "discover":
            progress_text = f"发现: 已扫描 {processed} 个文件"
        elif expected > 0:
            percent = int((processed / expected) * 100)
            progress_bar = self._make_progress_bar(percent, width=30)
            progress_text = f"进度: {progress_bar} {percent}% [{processed}/{expected}]"
        else:
            progress_text = f"进度: [{processed}/?]"
        
        # 状态图标和文本
        if stage == "success":
            status_icon = "✅"
            status_text = "下载"
            color_code = "\033[92m"  # 绿色
        elif stage == "skip":
            status_icon = "⏭️"
            status_text = "跳过"
            color_code = "\033[93m"  # 黄色
        elif stage == "failed":
            status_icon = "❌"
            status_text = "失败"
            color_code = "\033[91m"  # 红色
        elif stage == "start":
            status_icon = "⏳"
            status_text = "处理中"
            color_code = "\033[94m"  # 蓝色
        elif stage == "discover":
            status_icon = "🔍"
            status_text = "发现"
            color_code = "\033[96m"
        else:
            status_icon = "📂"
            status_text = "扫描"
            color_code = "\033[96m"  # 青色
        
        reset_code = "\033[0m"
        
        # 统计信息
        stats = []
        if self.downloaded > 0:
            stats.append(f"✅{self.downloaded}")
        if self.skipped > 0:
            stats.append(f"⏭️{self.skipped}")
        if self.failed > 0:
            stats.append(f"❌{self.failed}")
        
        stats_text = " ".join(stats) if stats else ""
        
        # 文件名（截断过长的名称）
        if name and stage in ("start", "success", "failed", "discover"):
            display_name = name[:35] + "..." if len(name) > 35 else name
            item_text = f" | {status_icon} {display_name}"
        else:
            item_text = ""
        
        # 组合完整的进度行
        if stage == "discover":
            line = f"{color_code}{progress_text}{reset_code}{item_text}"
        else:
            if stats_text:
                line = f"{color_code}{progress_text}{reset_code} | {stats_text}{item_text}"
            else:
                line = f"{color_code}{progress_text}{reset_code}{item_text}"
        
        return line
    
    def _make_progress_bar(self, percent: int, width: int = 20) -> str:
        """创建进度条"""
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return bar

    def _render(
        self,
        processed: int,
        expected: int,
        name: Optional[str],
        stage: str,
        file_type: Optional[str],
        detail: Optional[str],
    ) -> None:
        """统一渲染输出，避免重复代码。"""
        display_total = expected
        if stage != "discover" and self._limit is not None:
            display_total = self._limit
        self._flush_line()
        progress_text = self._format_progress_line(processed, display_total, name, stage, file_type, detail)
        sys.stdout.write(progress_text)
        sys.stdout.flush()
        self._last_line_length = len(progress_text)

    def _flush_line(self) -> None:
        if self._last_line_length > 0:
            sys.stdout.write('\r' + ' ' * self._last_line_length + '\r')
            sys.stdout.flush()
            self._last_line_length = 0
