"""Tkinter-based desktop entry point for LarkSync."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue

try:  # pragma: no cover - GUI import guard
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ModuleNotFoundError as exc:  # pragma: no cover - handled at runtime
    raise RuntimeError(
        "Tkinter is required to launch the local LarkSync tool but is not available."
    ) from exc

from ..bootstrap import build_runtime
from ..config import LarkSyncConfig
from ..core.models import SyncTask
from ..core.space_sync import DriveSpaceSynchronizer, SpaceSyncContext
from ..core.sync_engine import SyncEngine
from ..logging_utils import configure_logging
from ..storage import MetadataStore

_LOG_FORMAT = "%Y-%m-%d %H:%M:%S | %(levelname)s | %(message)s"


class QueueLogHandler(logging.Handler):
    """Redirect log records into the Tkinter queue."""

    def __init__(self, queue: Queue[tuple[str, str | None]]) -> None:
        super().__init__()
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - base signature
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - formatting safety net
            message = record.getMessage()
        self._queue.put(("log", message))


class LocalSyncApp:
    """Simple GUI wrapper around the existing sync engine."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("LarkSync 桌面工具")
        self.root.geometry("760x560")
        self.root.minsize(720, 520)

        self.access_token_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str((Path.cwd() / "output").resolve()))
        self.use_config_var = tk.BooleanVar(value=False)
        self.config_path_var = tk.StringVar()
        self.show_token_var = tk.BooleanVar(value=False)
        self.token_var = tk.StringVar()
        self.file_type_var = tk.StringVar(value="docx")
        self.name_var = tk.StringVar()
        self.limit_var = tk.StringVar(value="50")
        self.incremental_var = tk.BooleanVar(value=True)
        self.full_var = tk.BooleanVar(value=False)
        self.reset_metadata_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="准备就绪")

        self._queue: Queue[tuple[str, str | None]] = Queue()
        self._worker: threading.Thread | None = None
        self._progress_running = False
        self._token_entry: ttk.Entry | None = None
        self._config_entry: ttk.Entry | None = None
        self._config_button: ttk.Button | None = None
        self._progress_bar: ttk.Progressbar | None = None

        self._log_handler = QueueLogHandler(self._queue)
        self._log_handler.setLevel(logging.INFO)
        self._log_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        self._log_handler_attached = False

        self._build_layout()
        self._poll_queue()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        settings_frame = ttk.LabelFrame(container, text="基础设置")
        settings_frame.pack(fill=tk.X, expand=False, pady=(0, 12))
        settings_frame.columnconfigure(1, weight=1)

        ttk.Label(settings_frame, text="保存位置：").grid(row=0, column=0, sticky=tk.W, pady=(4, 0))
        output_entry = ttk.Entry(settings_frame, textvariable=self.output_dir_var)
        output_entry.grid(row=0, column=1, sticky=tk.EW, pady=(4, 0))
        ttk.Button(settings_frame, text="选择...", command=self._select_output_dir).grid(
            row=0, column=2, padx=(8, 0), pady=(4, 0)
        )

        ttk.Label(settings_frame, text="访问令牌（User Access Token）：").grid(
            row=1, column=0, sticky=tk.NW, pady=(12, 0)
        )
        token_frame = ttk.Frame(settings_frame)
        token_frame.grid(row=1, column=1, columnspan=2, sticky=tk.EW, pady=(12, 0))
        token_frame.columnconfigure(0, weight=1)
        self._token_entry = ttk.Entry(token_frame, textvariable=self.access_token_var, show="•")
        self._token_entry.grid(row=0, column=0, sticky=tk.EW)
        ttk.Checkbutton(
            token_frame,
            text="显示",
            variable=self.show_token_var,
            command=self._toggle_token_visibility,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(token_frame, text="获取说明", command=self._show_token_help).grid(
            row=0, column=2, padx=(8, 0)
        )

        ttk.Checkbutton(
            settings_frame,
            text="使用已有 config.toml（高级选项）",
            variable=self.use_config_var,
            command=self._update_config_usage,
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(12, 0))

        config_row = ttk.Frame(settings_frame)
        config_row.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(6, 0))
        config_row.columnconfigure(1, weight=1)
        ttk.Label(config_row, text="配置文件：").grid(row=0, column=0, sticky=tk.W)
        self._config_entry = ttk.Entry(config_row, textvariable=self.config_path_var, state=tk.DISABLED)
        self._config_entry.grid(row=0, column=1, sticky=tk.EW)
        self._config_button = ttk.Button(config_row, text="浏览...", command=self._select_config, state=tk.DISABLED)
        self._config_button.grid(row=0, column=2, padx=(8, 0))

        status_frame = ttk.Frame(container)
        status_frame.pack(fill=tk.X, expand=False, pady=(0, 12))
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)
        self._progress_bar = ttk.Progressbar(status_frame, mode="indeterminate", length=220)
        self._progress_bar.pack(side=tk.RIGHT)

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)

        download_tab = ttk.Frame(notebook, padding=12)
        notebook.add(download_tab, text="下载单个文档")
        self._build_download_tab(download_tab)

        sync_tab = ttk.Frame(notebook, padding=12)
        notebook.add(sync_tab, text="同步个人空间")
        self._build_sync_tab(sync_tab)

        log_frame = ttk.LabelFrame(container, text="运行日志")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.log_widget = ScrolledText(log_frame, height=12, state=tk.DISABLED)
        self.log_widget.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def _build_download_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="文档链接或 token：").grid(row=0, column=0, sticky=tk.W, pady=(0, 8))
        entry = ttk.Entry(parent, textvariable=self.token_var)
        entry.grid(row=0, column=1, sticky=tk.EW, pady=(0, 8))
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="类型：").grid(row=1, column=0, sticky=tk.W)
        type_box = ttk.Combobox(
            parent,
            textvariable=self.file_type_var,
            values=["docx", "doc", "sheet", "bitable", "file", "slides", "mindnote"],
            state="readonly",
        )
        type_box.grid(row=1, column=1, sticky=tk.W)

        ttk.Label(parent, text="自定义文件名（可选）：").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(parent, textvariable=self.name_var).grid(row=2, column=1, sticky=tk.EW, pady=(8, 0))

        ttk.Button(parent, text="开始下载", command=self._on_download).grid(row=3, column=0, columnspan=2, pady=16)

    def _build_sync_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="最大下载数量（0 表示全部）：").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(parent, textvariable=self.limit_var, width=10).grid(row=0, column=1, sticky=tk.W)

        ttk.Checkbutton(parent, text="增量更新（推荐）", variable=self.incremental_var).grid(
            row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 0)
        )
        ttk.Checkbutton(parent, text="强制全量下载", variable=self.full_var).grid(
            row=2, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Checkbutton(parent, text="清空缓存后再同步", variable=self.reset_metadata_var).grid(
            row=3, column=0, columnspan=2, sticky=tk.W
        )

        ttk.Button(parent, text="开始同步", command=self._on_sync).grid(row=4, column=0, columnspan=2, pady=16)
        parent.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _select_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择保存目录")
        if path:
            self.output_dir_var.set(path)

    def _select_config(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 config.toml",
            filetypes=[("TOML 文件", "*.toml"), ("所有文件", "*.*")],
        )
        if path:
            self.config_path_var.set(path)

    def _toggle_token_visibility(self) -> None:
        if not self._token_entry:
            return
        self._token_entry.config(show="" if self.show_token_var.get() else "•")

    def _update_config_usage(self) -> None:
        state = tk.NORMAL if self.use_config_var.get() else tk.DISABLED
        if self._config_entry and self._config_button:
            self._config_entry.config(state=state)
            self._config_button.config(state=state)
        if state == tk.DISABLED:
            self.config_path_var.set("")

    def _show_token_help(self) -> None:
        messagebox.showinfo(
            "如何获取访问令牌",
            (
                "请在飞书开放平台的“我的凭证”中获取个人 User Access Token。\n"
                "将令牌粘贴到此处后即可直接使用，无需额外配置文件。"
            ),
        )

    def _gather_base_settings(self) -> tuple[str, Path, Path | None] | None:
        token = self.access_token_var.get().strip()
        if not token:
            messagebox.showwarning("缺少信息", "请填写有效的 User Access Token。")
            return None

        output_text = self.output_dir_var.get().strip()
        if not output_text:
            messagebox.showwarning("缺少信息", "请选择文件保存位置。")
            return None
        output_dir = Path(output_text).expanduser().resolve()

        config_path: Path | None = None
        if self.use_config_var.get():
            config_text = self.config_path_var.get().strip()
            if not config_text:
                messagebox.showwarning("缺少信息", "请选择 config.toml 文件。")
                return None
            config_path = Path(config_text).expanduser()
            if not config_path.exists():
                messagebox.showwarning("文件不存在", "指定的 config.toml 无法找到，请重新选择。")
                return None

        return token, output_dir, config_path

    def _on_download(self) -> None:
        base_settings = self._gather_base_settings()
        if not base_settings:
            return
        access_token, output_dir, config_path = base_settings

        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("缺少信息", "请填写文档链接或 token。")
            return

        file_type = self.file_type_var.get().strip().lower()
        name = self.name_var.get().strip() or None

        def worker() -> None:
            error = False
            engine: SyncEngine | None = None
            config: LarkSyncConfig | None = None
            self._queue.put(("log", "开始下载文档..."))
            try:
                config, engine = self._build_engine(config_path, access_token, output_dir)
                try:
                    parsed_token, source_url = self._normalize_token(token)
                    task = SyncTask(
                        token=parsed_token,
                        file_type=file_type,
                        name=name or parsed_token,
                        parent_path=Path("."),
                        extra={"source_url": source_url} if source_url else {},
                    )
                    engine.process_task(task)
                    if config:
                        self._queue.put(("log", f"已下载 {file_type} {parsed_token} → {config.storage.root}"))
                finally:
                    if engine:
                        engine.close()
            except Exception as exc:  # pragma: no cover - GUI feedback
                error = True
                logging.getLogger(__name__).exception("下载任务失败")
                self._queue.put(("error", self._format_error(exc)))
            finally:
                self._detach_log_handler()
                self._queue.put(("done", "error" if error else "success"))

        self._start_worker(worker, "正在下载文档…")

    def _on_sync(self) -> None:
        base_settings = self._gather_base_settings()
        if not base_settings:
            return
        access_token, output_dir, config_path = base_settings

        limit_text = self.limit_var.get().strip()
        try:
            limit_value = int(limit_text)
        except ValueError:
            messagebox.showwarning("参数错误", "最大下载数量需要是整数。")
            return

        incremental = self.incremental_var.get()
        full = self.full_var.get()
        reset_metadata = self.reset_metadata_var.get()

        def worker() -> None:
            error = False
            engine: SyncEngine | None = None
            config: LarkSyncConfig | None = None
            self._queue.put(("log", "开始同步个人空间..."))
            try:
                config, engine = self._build_engine(config_path, access_token, output_dir)
                metadata_store = MetadataStore(engine.storage.root)
                try:
                    if reset_metadata:
                        metadata_store.clear()
                        metadata_store.flush()

                    effective_incremental = config.sync.enable_incremental if incremental else False
                    if full:
                        effective_incremental = False

                    context = SpaceSyncContext(
                        engine=engine,
                        drive=engine.drive_adapter,
                        registry=engine.registry,
                        storage=engine.storage,
                    )
                    synchronizer = DriveSpaceSynchronizer(
                        context,
                        metadata_store,
                        limit=None if limit_value <= 0 else limit_value,
                        incremental=effective_incremental,
                        force_on_missing=config.sync.force_download_missing,
                        clean_deleted=config.sync.clean_deleted,
                    )
                    synchronizer.sync()
                    if config:
                        self._queue.put(("log", f"同步完成 → {config.storage.root}"))
                finally:
                    if engine:
                        engine.close()
            except Exception as exc:  # pragma: no cover - GUI feedback
                error = True
                logging.getLogger(__name__).exception("空间同步失败")
                self._queue.put(("error", self._format_error(exc)))
            finally:
                self._detach_log_handler()
                self._queue.put(("done", "error" if error else "success"))

        self._start_worker(worker, "正在同步个人空间…")

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------
    def _build_engine(
        self,
        config_path: Path | None,
        access_token: str,
        output_dir: Path,
    ) -> tuple[LarkSyncConfig, SyncEngine]:
        overrides = {
            "auth": {"user_access_token": access_token},
            "storage": {"root": output_dir},
            "logging": {"structured": False},
        }
        config, client, storage, registry = build_runtime(config_path, overrides)
        configure_logging(config.logging)
        self._attach_log_handler()
        engine = SyncEngine(config=config, client=client, registry=registry, storage=storage)
        return config, engine

    @staticmethod
    def _normalize_token(token: str) -> tuple[str, str | None]:
        if "://" in token:
            cleaned = token.rstrip("/").split("/")[-1]
            cleaned = cleaned.split("?")[0].split("#")[0]
            return cleaned, token.strip()
        cleaned = token.split("?")[0].split("#")[0]
        return cleaned, None

    def _format_error(self, exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        return (
            f"{message}\n\n如果问题持续出现，请检查访问令牌是否有效，"
            "或参考日志获取更多细节。"
        )

    def _attach_log_handler(self) -> None:
        if not self._log_handler_attached:
            logging.getLogger().addHandler(self._log_handler)
            self._log_handler_attached = True

    def _detach_log_handler(self) -> None:
        if self._log_handler_attached:
            try:
                logging.getLogger().removeHandler(self._log_handler)
            finally:
                self._log_handler_attached = False

    # ------------------------------------------------------------------
    # Thread handling & logging
    # ------------------------------------------------------------------
    def _start_worker(self, target: Callable[[], None], status_message: str) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("任务执行中", "当前仍有任务在运行，请稍候。")
            return

        self._set_status(status_message, running=True)
        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log" and payload:
                    self._append_log(payload)
                elif kind == "error" and payload:
                    self._append_log(payload)
                    self._set_status("运行失败，请查看日志", running=False)
                    messagebox.showerror("运行出错", payload)
                elif kind == "done":
                    self._worker = None
                    if payload == "error":
                        self._append_log("任务结束（发生错误）。")
                        self._set_status("任务结束，发生错误", running=False)
                    else:
                        self._append_log("任务完成。")
                        self._set_status("任务完成", running=False)
        except Empty:
            pass
        finally:
            self.root.after(150, self._poll_queue)

    def _set_status(self, message: str, running: bool = False) -> None:
        self.status_var.set(message)
        if not self._progress_bar:
            return
        if running and not self._progress_running:
            self._progress_bar.start(10)
            self._progress_running = True
        elif not running and self._progress_running:
            self._progress_bar.stop()
            self._progress_running = False

    def _append_log(self, message: str) -> None:
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Start the Tkinter main loop."""
        self.root.mainloop()


def run() -> None:
    """Entry point for console script."""
    app = LocalSyncApp()
    app.run()
