import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Cpu,
  ExternalLink,
  FolderOpen,
  Layers,
  Mic,
  Plug,
  RefreshCw,
  Server,
  Settings2,
  Wifi,
  X,
} from "lucide-react";
import type React from "react";
import { useEffect, useId, useRef, useState } from "react";
import type { AppUpdateInfo } from "../api";
import { checkServerHealth, fetchServerPort, saveServerPort, fetchRemoteAccess, type RemoteAccessInfo } from "../api";
import type { AppSettings, VoiceOption } from "../types";
import { UpdateCheckToggle } from "./AppUpdate";
import { DefaultVoicePicker } from "./DefaultVoicePicker";
import { GpuMemoryPanel } from "./GpuMemoryPanel";
import { ModelManager } from "./ModelManager";
import { RemoteAccessPanel } from "./RemoteAccessPanel";
import { RestartNotice, useAppRestart } from "./RestartNotice";
import { SaveSettingsPanel } from "./SaveSettingsPanel";

const TRAILING_SLASH = /\/$/;

/** Giao diện do chính máy chủ phục vụ (app desktop, trình duyệt mở cổng 8001) thì
 *  luôn gọi đúng máy chủ đó - ô địa chỉ chỉ cần cho Vite dev hoặc khi đã
 *  trỏ sang máy chủ khác. */
function needsServiceUrl(current: string): boolean {
  const { origin, protocol } = window.location;
  return (
    import.meta.env.DEV ||
    !protocol.startsWith("http") ||
    current.replace(TRAILING_SLASH, "") !== origin
  );
}

// Chỉ liệt kê API công khai, khớp với /openapi.json và cit-voice-studio.md.
// Khi thêm đường dẫn API công khai, cập nhật danh sách này.
const API_ENDPOINTS = [
  { method: "GET", path: "/health", desc: "Trạng thái máy chủ, tên mô hình" },
  { method: "GET", path: "/voices", desc: "Danh sách giọng đọc" },
  { method: "POST", path: "/stream", desc: "Đọc theo thời gian thực (PCM)" },
  { method: "POST", path: "/api/tts/generate", desc: "Văn bản thành WAV/MP3" },
  {
    method: "POST",
    path: "/api/tts/generate-with-subtitles",
    desc: "Audio kèm phụ đề .srt",
  },
  {
    method: "POST",
    path: "/api/tts/conversation",
    desc: "Hội thoại nhiều người nói",
  },
  {
    method: "GET",
    path: "/cit-voice-studio.md",
    desc: "Tài liệu Markdown cho AI Agent",
  },
] as const;

const SETTINGS_SECTIONS = [
  {
    id: "models",
    label: "Mô hình AI",
    icon: Layers,
    description: "Chọn mô hình phù hợp với máy và nhu cầu đọc của bạn.",
  },
  {
    id: "voice",
    label: "Giọng đọc",
    icon: Mic,
    description: "Giọng đọc được chọn sẵn khi mở ứng dụng.",
  },
  {
    id: "files",
    label: "Lưu file",
    icon: FolderOpen,
    description: "Thư mục lưu audio, phụ đề và việc mở file sau khi lưu.",
  },
  {
    id: "connection",
    label: "Kết nối",
    icon: Server,
    description: "Cổng máy chủ của ứng dụng.",
  },
  {
    id: "network",
    label: "Mạng LAN",
    icon: Wifi,
    description: "Quản lý quyền gọi API từ các máy trong cùng mạng.",
  },
  {
    id: "updates",
    label: "Cập nhật & thông tin",
    icon: RefreshCw,
    description: "Tuỳ chọn kiểm tra phiên bản mới và thông tin âm thanh.",
  },
  {
    id: "api",
    label: "Tích hợp API",
    icon: Plug,
    description: "Kết nối CIT Voice Studio với ứng dụng và quy trình của bạn.",
  },
] as const;
type SettingsSection = (typeof SETTINGS_SECTIONS)[number]["id"];
const FOCUSABLE =
  'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]';

function handleDialogKey(
  event: KeyboardEvent,
  dialog: HTMLElement,
  onClose: () => void
) {
  if (event.key === "Escape") {
    event.stopPropagation();
    onClose();
    return;
  }
  if (event.key !== "Tab") {
    return;
  }
  const elements = Array.from(
    dialog.querySelectorAll<HTMLElement>(FOCUSABLE)
  ).filter((element) => element.getClientRects().length > 0);
  const first = elements[0];
  const last = elements.pop();
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}

interface SettingsModalProps {
  initialSection?: "models";
  isOpen: boolean;
  onClose: () => void;
  onModelSwitched?: (modelName: string) => void;
  onSaveSettings: (settings: AppSettings) => void;
  /** Kết quả kiểm tra phiên bản sau khi bật tự kiểm tra cập nhật. */
  onUpdateChecked?: (info: AppUpdateInfo) => void;
  settings: AppSettings;
  voices: VoiceOption[];
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  initialSection,
  onClose,
  settings,
  onSaveSettings,
  onModelSwitched,
  onUpdateChecked,
  voices,
}) => {
  const [deploymentInfo, setDeploymentInfo] = useState<RemoteAccessInfo | null>(null);
  const hosted = deploymentInfo?.mode === "selfhost";
  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    fetchRemoteAccess(settings.apiUrl, controller.signal).then(setDeploymentInfo).catch(() => setDeploymentInfo(null));
    return () => controller.abort();
  }, [isOpen, settings.apiUrl]);
  const titleId = useId();
  const urlId = useId();
  const portId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [section, setSection] = useState<SettingsSection>("models");
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    setSection(initialSection ?? "models");
    const previous = document.activeElement;
    closeRef.current?.focus();
    return () => {
      if (previous instanceof HTMLElement) {
        previous.focus();
      }
    };
  }, [isOpen, initialSection]);
  useEffect(() => {
    if (section && isOpen) {
      contentRef.current?.scrollTo({ top: 0 });
    }
  }, [section, isOpen]);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!(isOpen && dialog)) {
      return;
    }
    const handleKey = (event: KeyboardEvent) =>
      handleDialogKey(event, dialog, onClose);
    dialog.addEventListener("keydown", handleKey);
    return () => dialog.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);
  const [apiUrl, setApiUrl] = useState(settings.apiUrl);
  useEffect(() => {
    if (isOpen) {
      setApiUrl(settings.apiUrl);
      setTestStatus("idle");
      setTestMessage("");
    }
  }, [isOpen, settings.apiUrl]);
  const [testStatus, setTestStatus] = useState<
    "idle" | "testing" | "success" | "error"
  >("idle");
  const [testMessage, setTestMessage] = useState("");
  const [copiedExample, setCopiedExample] = useState(false);
  const [serverPort, setServerPort] = useState("8001");
  const [activePort, setActivePort] = useState<number | null>(null);
  const [portMessage, setPortMessage] = useState("");
  const [portReady, setPortReady] = useState(false);
  const [portSaving, setPortSaving] = useState(false);
  // Cổng đã lưu khác cổng đang chạy thì cần thông báo khởi động lại.
  const [pendingPort, setPendingPort] = useState<number | null>(null);
  const appRestart = useAppRestart(settings.apiUrl);
  // Tăng khi đổi mô hình: GpuMemoryPanel mount lại để đọc trạng thái GPU mới.
  const [modelVersion, setModelVersion] = useState(0);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const controller = new AbortController();
    setPortReady(false);
    setPortMessage("Đang đọc cấu hình cổng server...");
    fetchServerPort(settings.apiUrl, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) {
          return;
        }
        setServerPort(String(result.port));
        setActivePort(result.active_port);
        setPortReady(true);
        setPendingPort(result.port === result.active_port ? null : result.port);
        setPortMessage("");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setPortMessage(
            "Không đọc được cấu hình cổng. Hãy kết nối tới server và mở lại Cài đặt."
          );
        }
      });
    return () => controller.abort();
  }, [isOpen, settings.apiUrl]);

  const handleSavePort = async (andRestart = false) => {
    const port = Number(serverPort);
    if (
      !(/^\d+$/.test(serverPort) && Number.isInteger(port)) ||
      port < 1 ||
      port > 65_535
    ) {
      setPortMessage("Nhập số cổng từ 1 đến 65535.");
      return;
    }
    setPortSaving(true);
    setPortMessage("Đang lưu cổng server...");
    try {
      const result = await saveServerPort(settings.apiUrl, port);
      setActivePort(result.active_port);
      if (result.port === result.active_port) {
        setPendingPort(null);
        setPortMessage(
          `✓ Đã lưu. Cổng ${result.port} đang chạy sẵn, không cần khởi động lại.`
        );
        return;
      }
      setPendingPort(result.port);
      setPortMessage("");
      if (andRestart) {
        await appRestart.restart();
      }
    } catch {
      setPortMessage(
        "Không lưu được cổng server. Kiểm tra kết nối và thử lại."
      );
    } finally {
      setPortSaving(false);
    }
  };

  const publicApiBase = deploymentInfo?.public_api_url ?? apiUrl.replace(TRAILING_SLASH, "");
  const apiExample = `import json, os, urllib.request

base = "${publicApiBase}"
headers = {"Content-Type": "application/json", "X-API-Key": os.environ["VOICE_API_KEY"]}
# Lấy một giọng hiện dùng được thay vì gắn cứng giọng của mô hình khác.
with urllib.request.urlopen(urllib.request.Request(base + "/voices", headers=headers)) as r:
    voice = json.load(r)[0]
text = {"ja": "こんにちは。", "zh": "你好。", "en": "Hello."}.get(voice.get("language"), "Xin chào")
body = json.dumps({"text": text, "voice_id": voice["id"], "format": "wav"}).encode()
req = urllib.request.Request(base + "/api/tts/generate", data=body, headers=headers)
with urllib.request.urlopen(req, timeout=180) as r:
    open("giong-noi.wav", "wb").write(r.read())`;

  const handleCopyExample = () => {
    navigator.clipboard.writeText(apiExample);
    setCopiedExample(true);
    setTimeout(() => setCopiedExample(false), 2000);
  };

  if (!isOpen) {
    return null;
  }

  const handleTestConnection = async () => {
    setTestStatus("testing");
    setTestMessage("Đang kiểm tra kết nối...");
    try {
      const res = await checkServerHealth(apiUrl.trim());
      if (res.status === "loading") {
        setTestStatus("success");
        setTestMessage(
          `Đã kết nối tới dịch vụ. ${res.message || "Mô hình đang nạp, vui lòng chờ."}`
        );
        return;
      }
      if (res.status === "error") {
        setTestStatus("error");
        setTestMessage(
          `Đã kết nối tới dịch vụ, nhưng mô hình gặp lỗi: ${res.message || "Không nạp được mô hình."}`
        );
        return;
      }
      if (res.status !== "ok") {
        throw new Error("Máy chủ trả về trạng thái không hợp lệ.");
      }
      setTestStatus("success");
      setTestMessage(
        `Kết nối thành công! Server: ${res.engine} (Tần số: ${res.sample_rate / 1000} kHz)`
      );
    } catch (e) {
      setTestStatus("error");
      setTestMessage(
        `Lỗi kết nối: ${e instanceof Error ? e.message : String(e)}`
      );
    }
  };

  // Mỗi mục tự lưu tại chỗ; địa chỉ dịch vụ có nút Lưu riêng như cổng.
  const handleSaveUrl = () => {
    // Lưu xong nút tự mờ (địa chỉ đã khớp cấu hình) - đủ báo đã lưu.
    onSaveSettings({ ...settings, apiUrl: apiUrl.trim() });
  };

  const sections = SETTINGS_SECTIONS.map(item => hosted && item.id === "network" ? { ...item, label: "API qua HTTPS", description: "Domain công khai và khóa cho ứng dụng bên ngoài." } : item);
  const currentSection =
    sections.find((item) => item.id === section) ??
    SETTINGS_SECTIONS[0];

  const apiBase = publicApiBase;
  const showServiceUrl = needsServiceUrl(settings.apiUrl);

  return (
    <div
      aria-labelledby={titleId}
      aria-modal="true"
      className="settings-overlay fixed inset-0 z-[60]"
      ref={dialogRef}
      role="dialog"
    >
      <div className="settings-dialog">
        <header className="settings-header">
          <div className="flex items-center gap-3">
            <span className="settings-header-icon">
              <Settings2 size={22} />
            </span>
            <div>
              <h2 id={titleId}>Cài đặt</h2>
              <p>CIT Voice Studio · Tuỳ chỉnh không gian làm việc</p>
            </div>
          </div>
          <button
            aria-label="Đóng cài đặt"
            className="studio-icon-button"
            onClick={onClose}
            ref={closeRef}
            type="button"
          >
            <X size={20} />
          </button>
        </header>
        <div className="settings-body">
          <nav aria-label="Danh mục cài đặt" className="settings-nav">
            <span className="settings-nav-label">Tuỳ chỉnh ứng dụng</span>
            {sections.map((item) => (
              <button
                aria-current={section === item.id ? "page" : undefined}
                key={item.id}
                onClick={() => setSection(item.id)}
                type="button"
              >
                <item.icon aria-hidden="true" size={18} />
                <span>{item.label}</span>
              </button>
            ))}
          </nav>
          <div className="settings-content" ref={contentRef}>
            <div className="settings-section-title">
              <h3>{currentSection.label}</h3>
              <p>{currentSection.description}</p>
            </div>
            <div className="settings-section" hidden={section !== "models"}>
              <ModelManager
                apiUrl={apiUrl}
                embedded
                enabled={isOpen}
                initialExpanded
                onModelSwitched={(modelName) => {
                  setModelVersion((v) => v + 1);
                  onModelSwitched?.(modelName);
                }}
              />
              <GpuMemoryPanel
                apiUrl={apiUrl}
                enabled={isOpen}
                key={modelVersion}
              />
            </div>
            <div className="settings-section" hidden={section !== "voice"}>
              <div className="settings-card">
                <DefaultVoicePicker
                  active={isOpen && section === "voice"}
                  onChange={(defaultVoiceId) =>
                    onSaveSettings({ ...settings, defaultVoiceId })
                  }
                  value={settings.defaultVoiceId ?? ""}
                  voices={voices}
                />
              </div>
            </div>
            <div className="settings-section" hidden={section !== "connection"}>
              {/* Địa chỉ dịch vụ: app desktop luôn nối máy chủ của chính nó (và xoá
                  localStorage mỗi lần mở), nên chỉ hiện khi giao diện chạy ở nơi khác. */}
              {showServiceUrl && (
                <div className="settings-card space-y-3">
                  <label className="settings-card-title" htmlFor={urlId}>
                    Địa chỉ dịch vụ giọng nói
                  </label>
                  <p className="settings-help">
                    Giữ địa chỉ mặc định nếu dịch vụ chạy trên máy này.
                  </p>
                  <div className="settings-field-row">
                    <input
                      className="min-w-0 flex-1 rounded-xl border border-border bg-secondary/50 px-3 py-2 font-mono text-xs outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
                      id={urlId}
                      onChange={(e) => {
                        setApiUrl(e.target.value);
                        setTestStatus("idle");
                      }}
                      placeholder="http://127.0.0.1:8001"
                      type="text"
                      value={apiUrl}
                    />
                    <button
                      className="flex items-center gap-1 rounded-xl border border-border bg-secondary px-3 py-2 font-medium transition-all hover:bg-secondary/80"
                      disabled={testStatus === "testing"}
                      onClick={handleTestConnection}
                      type="button"
                    >
                      {testStatus === "testing" ? (
                        <>
                          <RefreshCw className="h-3.5 w-3.5 animate-spin text-amber-500" />
                          <span>Đang kiểm tra...</span>
                        </>
                      ) : (
                        <span>Kiểm tra</span>
                      )}
                    </button>
                    <button
                      className="studio-primary rounded-xl px-3 py-2 disabled:opacity-50"
                      disabled={apiUrl.trim() === settings.apiUrl}
                      onClick={handleSaveUrl}
                      type="button"
                    >
                      Lưu
                    </button>
                  </div>
                  {testStatus !== "idle" && (
                    <div
                      aria-live="polite"
                      className={`mt-2 flex items-start gap-2 rounded-xl border p-2.5 text-[12px] ${
                        testStatus === "success"
                          ? "border-brand-500/30 bg-brand-500/10 text-brand-600 dark:text-brand-400"
                          : testStatus === "error"
                            ? "border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400"
                            : "bg-muted text-muted-foreground"
                      }`}
                      role="status"
                    >
                      {testStatus === "success" ? (
                        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      ) : (
                        <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      )}
                      <span>{testMessage}</span>
                    </div>
                  )}
                </div>
              )}

              {hosted ? (
                <div className="settings-card space-y-3">
                  <h4 className="settings-card-title">Máy chủ VPS</h4>
                  <p className="settings-help">Địa chỉ quản lý: {deploymentInfo?.public_url}</p>
                  <p className="settings-help">Base URL API: {publicApiBase}</p>
                  <p className="settings-help">Domain, cổng nội bộ, cập nhật và khởi động lại được quản lý trong Coolify. Không cần đổi cổng hoặc cấu hình tường lửa trên máy cá nhân.</p>
                  <p className="settings-help"><a className="underline" href="/saas/admin" target="_blank" rel="noreferrer">Quản trị SaaS: khách hàng và gói dịch vụ</a></p>
                  <p className="settings-help"><a className="underline" href="/saas/" target="_blank" rel="noreferrer">Mở cổng khách hàng</a></p>
                </div>
              ) : (
              <div className="settings-card space-y-3">
                <label className="settings-card-title" htmlFor={portId}>
                  Cổng khi khởi động ứng dụng
                </label>
                <p className="settings-help">
                  Mặc định 8001
                  {activePort === null ? "" : ` · Đang chạy: ${activePort}`}.
                  Nếu cổng bận, app chọn cổng trống tiếp theo.
                </p>
                <div className="settings-field-row">
                  <input
                    className="min-w-0 flex-1 rounded-xl border border-border bg-secondary/50 px-3 py-2"
                    disabled={!portReady || portSaving}
                    id={portId}
                    max={65_535}
                    min={1}
                    onChange={(event) => setServerPort(event.target.value)}
                    step={1}
                    type="number"
                    value={serverPort}
                  />
                  <button
                    className="rounded-xl border border-border px-3 py-2 disabled:opacity-50"
                    disabled={!portReady || portSaving}
                    onClick={() => setServerPort("8001")}
                    type="button"
                  >
                    Mặc định 8001
                  </button>
                  <button
                    className="studio-primary rounded-xl bg-brand-600 px-3 py-2 text-white disabled:opacity-50"
                    disabled={!portReady || portSaving}
                    onClick={() => handleSavePort()}
                    type="button"
                  >
                    {portSaving ? "Đang lưu..." : "Lưu cổng"}
                  </button>
                </div>
                {appRestart.supported && (
                  <button
                    className="w-full rounded-xl border border-brand-600/60 px-3 py-2 font-semibold text-brand-700 hover:bg-brand-500/10 disabled:opacity-50 dark:text-brand-300"
                    disabled={!portReady || portSaving || appRestart.restarting}
                    onClick={() => handleSavePort(true)}
                    type="button"
                  >
                    Lưu &amp; khởi động lại
                  </button>
                )}
                {appRestart.restarting ? (
                  <p
                    aria-live="polite"
                    className="font-medium text-amber-700 dark:text-amber-300"
                    role="status"
                  >
                    Đang khởi động lại… cửa sổ sẽ đóng rồi tự mở lại sau vài
                    giây.
                  </p>
                ) : pendingPort === null ? null : (
                  <RestartNotice
                    apiUrl={settings.apiUrl}
                    message={`Đã lưu cổng ${pendingPort}.`}
                  />
                )}
                {appRestart.error && (
                  <p className="text-rose-600 dark:text-rose-400" role="alert">
                    {appRestart.error}
                  </p>
                )}
                {portMessage && (
                  <p
                    aria-live="polite"
                    className="text-muted-foreground"
                    role="status"
                  >
                    {portMessage}
                  </p>
                )}
              </div>
              )}
            </div>
            <div className="settings-section" hidden={section !== "network"}>
              <RemoteAccessPanel apiUrl={settings.apiUrl} isOpen={isOpen} />
            </div>
            <div className="settings-section" hidden={section !== "files"}>
              <SaveSettingsPanel isOpen={isOpen} />
            </div>
            <div className="settings-section" hidden={section !== "updates"}>
              {hosted ? <div className="settings-card"><p className="settings-help">Bản self-host được cập nhật bằng build và redeploy trong Coolify. Dữ liệu mô hình, giọng và lịch sử nằm trên volume máy chủ.</p></div> : <UpdateCheckToggle apiUrl={settings.apiUrl} isOpen={isOpen} onChecked={onUpdateChecked} />}

              {/* Thông tin tính năng âm thanh. */}
              <div className="settings-card space-y-3">
                <h4 className="settings-card-title">
                  <Cpu size={16} />
                  Thông tin âm thanh
                </h4>
                <dl className="settings-facts">
                  <div>
                    <dt>Tần số mẫu</dt>
                    <dd>{settings.sampleRate.toLocaleString("vi-VN")} Hz</dd>
                  </div>
                  <div>
                    <dt>Nhân bản giọng</dt>
                    <dd>Đọc câu đồng ý qua micro</dd>
                  </div>
                  <div>
                    <dt>Hội thoại</dt>
                    <dd>Nhiều người nói</dd>
                  </div>
                  <div>
                    <dt>Định dạng xuất</dt>
                    <dd>WAV, MP3</dd>
                  </div>
                </dl>
              </div>
            </div>
            <div className="settings-section" hidden={section !== "api"}>
              {/* Tài liệu đặt đầu mục: người tích hợp cần nó trước tiên. */}
              <div className="settings-card settings-docs">
                <div className="settings-docs-text">
                  <h4 className="settings-card-title">
                    <BookOpen size={16} />
                    Tài liệu API
                  </h4>
                  <p className="settings-help">
                    Mô tả đầy đủ tham số và thử gọi trực tiếp trên trình duyệt.
                  </p>
                </div>
                <div className="settings-docs-actions">
                  <a
                    className="settings-docs-primary"
                    href={`${apiBase}/docs`}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Mở tài liệu (Swagger)
                    <ExternalLink size={14} />
                  </a>
                  <a
                    className="settings-docs-secondary"
                    href={`${apiBase}/cit-voice-studio.md`}
                    rel="noreferrer"
                    target="_blank"
                    title="Tài liệu Markdown để đưa cho AI Agent (ChatGPT, Claude…)"
                  >
                    Bản cho AI Agent (.md)
                    <ExternalLink size={14} />
                  </a>
                </div>
              </div>
              <div className="settings-card">
                <div className="space-y-4">
                  <p className="settings-help">
                    {hosted ? <>Gọi qua <code>{publicApiBase}</code> và gửi header <code>X-API-Key</code> hoặc <code>Authorization: Bearer</code>. Lấy khóa tại mục API qua HTTPS. Không cần mật khẩu web; API không cho quản lý mô hình hay lịch sử. Mô hình được chọn dùng chung giữa web và API.</> : <>Ứng dụng khác trên cùng máy gọi được API trực tiếp. Với máy khác, bật Mạng LAN và gửi khóa API.</>}
                  </p>

                  <div className="settings-api-table">
                    <table className="w-full">
                      <thead>
                        <tr>
                          <th scope="col">Phương thức</th>
                          <th scope="col">Đường dẫn</th>
                          <th scope="col">Chức năng</th>
                        </tr>
                      </thead>
                      <tbody>
                        {API_ENDPOINTS.map((e) => (
                          <tr key={e.path + e.method}>
                            <td>
                              <span
                                className="settings-method"
                                data-method={e.method}
                              >
                                {e.method}
                              </span>
                            </td>
                            <td className="font-mono">{e.path}</td>
                            <td>{e.desc}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <h4 className="settings-card-title">
                        Ví dụ tạo giọng nói
                      </h4>
                      <button
                        className="flex items-center gap-1 rounded-md border border-border/60 bg-secondary px-2 py-1 font-medium transition-colors hover:bg-secondary/80"
                        onClick={handleCopyExample}
                        type="button"
                      >
                        {copiedExample ? (
                          <>
                            <CheckCircle2 className="h-3 w-3 text-brand-500" />
                            <span className="text-brand-500">Đã chép</span>
                          </>
                        ) : (
                          <span>Sao chép</span>
                        )}
                      </button>
                    </div>
                    <pre className="select-all overflow-x-auto rounded-lg bg-zinc-950 p-3 font-mono text-[12.5px] text-zinc-200 leading-relaxed">
                      {apiExample}
                    </pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        {/* Mọi thay đổi đã lưu tại chỗ, chân hộp thoại chỉ còn nút Đóng. */}
        <div className="settings-footer">
          <button
            className="ml-auto rounded-xl border border-border px-4 py-1.5 text-muted-foreground transition-all hover:bg-secondary hover:text-foreground"
            onClick={onClose}
            type="button"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
};
