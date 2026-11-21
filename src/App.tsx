import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bell,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  Clock3,
  FileCheck2,
  Filter,
  Headphones,
  Home,
  Eye,
  EyeOff,
  LayoutDashboard,
  LocateFixed,
  LogIn,
  MapPin,
  Menu,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  UserRoundPlus,
  X,
} from "lucide-react";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
} from "react-leaflet";

type Role = "citizen" | "engineer" | "engineer_pending" | "verifier" | "officer" | "admin";
type Page = "Home" | "Government schemes" | "Work tracking" | "Reports" | "Engineer registration";
type Severity = "Critical" | "High" | "Medium" | "Low";
type AssignedEngineer = {
  id?: string;
  name: string;
  department: string;
  registration_number: string;
  skills: string[];
};
type Complaint = {
  id: string;
  reference: string;
  title: string;
  description: string;
  category: string;
  severity: Severity;
  official_status: string;
  engineer_work_status: string;
  verification_status: string;
  ward: string;
  address: string;
  latitude: number;
  longitude: number;
  location_accuracy_meters?: number | null;
  location_captured_at?: string | null;
  department: string;
  engineer_id?: string | null;
  verifier_id?: string | null;
  assigned_engineer?: AssignedEngineer | null;
  assessment?: {
    suggested_category: string;
    suggested_severity: Severity;
    suggested_department: string;
    summary: string;
    rationale: string;
    confidence: number;
    duplicate_references: string[];
    rules_version: string;
  } | null;
};
type PublicDashboard = {
  counts: {
    total_reports: number;
    open: number;
    awaiting_verification: number;
    resolved: number;
    high_priority: number;
  };
  by_category: Record<string, number>;
  complaints: {
    reference: string;
    title: string;
    category: string;
    severity: Severity;
    official_status: string;
    engineer_work_status: string;
    verification_status: string;
    ward: string;
    latitude: number;
    longitude: number;
    department: string;
    created_at: string;
  }[];
};
type ComplaintFeedback = { rating: number; comment: string; submitted_at: string };
type ComplaintAttachment = {
  id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
};
type CurrentUser = { id: string; name: string; email: string; role: Role };
type WorkspaceNotification = { id: string; title: string; detail: string; page: Page };
type CapturedLocation = {
  latitude: number;
  longitude: number;
  accuracy: number;
  capturedAt: string;
};
type AuthResponse = { access_token: string; token_type: "bearer"; user: CurrentUser };
type EngineerApplication = {
  user_id: string;
  name: string;
  email: string;
  department: string;
  registration_number: string;
  skills: string[];
  application_note: string;
};
type EngineerOption = {
  id: string;
  name: string;
  department: string;
  registration_number: string;
  skills: string[];
};
type WorkEvent = {
  event_type: string;
  note: string;
  actor: string;
  created_at: string;
  latitude?: number | null;
  longitude?: number | null;
  before_evidence?: string;
  after_evidence?: string;
  attempt_number?: number;
  captured_at?: string;
};
type SchemeTaskUpdate = {
  event_type: string;
  note: string;
  actor: string;
  created_at: string;
};
type SchemeTask = {
  id: string;
  scheme_title: string;
  title: string;
  description: string;
  department: string;
  required_skills: string[];
  status: string;
  assigned_engineer: AssignedEngineer | null;
  progress_note?: string;
  updates?: SchemeTaskUpdate[];
  created_at: string;
  updated_at: string;
};
type LiveWorkLocation = {
  work_type: "complaint" | "scheme";
  work_id: string;
  title: string;
  reference: string | null;
  scheme_title: string | null;
  status: string;
  assigned_engineer: AssignedEngineer;
  latitude: number;
  longitude: number;
  updated_at: string;
};
type LiveLocationWatch = {
  watchId: number;
  lastPosition: GeolocationPosition | null;
  lastSentAt: number;
  path: string;
};
type EngineerRegistrationProfile = {
  registration_status: string;
  department: string;
  registration_number: string;
  skills: string[];
  application_note: string;
  reviews: { decision: string; reason: string; reviewed_at: string }[];
};
type VerificationItem = {
  complaint: Complaint;
  submission: {
    id: string;
    work_details: string;
    completion_notes: string;
    before_evidence: string;
    after_evidence: string;
    latitude: number;
    longitude: number;
    captured_at: string;
    location_accuracy_meters: number | null;
    location_captured_at: string | null;
    distance_from_complaint_meters: number;
    distance_review_flag: boolean;
    attempt_number: number;
  };
};
type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: { title: string; source_url: string; version: string; excerpt: string }[];
};
type SchemeDocument = { title: string; source_url: string; version: string };
type AdminAccount = {
  id: string;
  name: string;
  email: string;
  role: Role;
  account_status: "ACTIVE" | "INACTIVE";
  email_verified: boolean;
};
type ProfileData = {
  id: string;
  name: string;
  email: string;
  role: Role;
  email_verified: boolean;
  account_status: "ACTIVE" | "INACTIVE";
  phone_number: string;
  address?: string;
  ward?: string;
  official?: {
    department: string;
    employee_id: string;
    designation: string;
    jurisdiction: string;
    registration_status?: string;
  };
};

const roleLabels: Record<Role, string> = {
  citizen: "Citizen",
  engineer: "Registered engineer",
  engineer_pending: "Engineer application pending",
  verifier: "Verification officer",
  officer: "Government officer",
  admin: "Administrator",
};

const DEFAULT_MAP_CENTER: [number, number] = [12.9716, 77.6136];

function requestCurrentLocation(): Promise<CapturedLocation> {
  if (!navigator.geolocation) {
    return Promise.reject(new Error("This browser does not support device location."));
  }
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
        capturedAt: new Date(position.timestamp).toISOString(),
      }),
      (error) => {
        const message =
          error.code === error.PERMISSION_DENIED
            ? "Location permission was denied. You can enter coordinates manually."
            : "Could not get your location. Check device location settings and try again.";
        reject(new Error(message));
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    );
  });
}

async function compressEvidenceImage(file: File): Promise<string> {
  if (!file.type.startsWith("image/")) {
    throw new Error("Choose an image file.");
  }
  if (file.size > 12 * 1024 * 1024) {
    throw new Error("Choose a photo smaller than 12 MB.");
  }

  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const loadedImage = new Image();
    loadedImage.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(loadedImage);
    };
    loadedImage.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("The selected photo could not be opened."));
    };
    loadedImage.src = objectUrl;
  });
  const scale = Math.min(1, 1280 / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(image.naturalWidth * scale);
  canvas.height = Math.round(image.naturalHeight * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Photo processing is not available in this browser.");
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  for (const quality of [0.82, 0.72, 0.62, 0.52]) {
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality),
    );
    if (blob && blob.size <= 900 * 1024) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          if (typeof reader.result === "string") resolve(reader.result);
          else reject(new Error("The selected photo could not be processed."));
        };
        reader.onerror = () => reject(new Error("The selected photo could not be processed."));
        reader.readAsDataURL(blob);
      });
    }
  }
  throw new Error("This photo is too detailed to upload. Choose a smaller image.");
}

const navItems: { name: Page; icon: typeof LayoutDashboard }[] = [
  { name: "Home", icon: Home },
  { name: "Government schemes", icon: BookOpen },
  { name: "Work tracking", icon: CheckCircle2 },
  { name: "Reports", icon: FileCheck2 },
  { name: "Engineer registration", icon: UserRoundPlus },
];

const featuredSchemes = [
  {
    title: "Pradhan Mantri Awas Yojana – Urban 2.0",
    category: "Urban housing",
    description: "Housing support for eligible urban households. Check current eligibility and application details on the official portal.",
    source_url: "https://pmay-urban.gov.in/",
  },
  {
    title: "PM Street Vendor’s AtmaNirbhar Nidhi",
    category: "Street-vendor support",
    description: "A micro-credit facility for street vendors. Check current terms and application details on the official portal.",
    source_url: "https://pmsvanidhi.mohua.gov.in/",
  },
  {
    title: "Swachh Bharat Mission – Urban",
    category: "Sanitation & waste",
    description: "Urban sanitation and waste-management mission information, including state and city progress.",
    source_url: "https://sbmurban.org/",
  },
  {
    title: "Ayushman Bharat PM-JAY",
    category: "Health coverage",
    description: "Health coverage information for eligible families. Verify current eligibility through the National Health Authority.",
    source_url: "https://nha.gov.in/PM-JAY",
  },
];

function statusLabel(status: string) {
  return status.replace(/_/g, " ").toLowerCase().replace(/^\w/, (letter: string) => letter.toUpperCase());
}

function dateTimeLocalValue(date: Date) {
  const localTime = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localTime.toISOString().slice(0, 16);
}

function severityClass(severity: Severity) {
  return `severity severity-${severity.toLowerCase()}`;
}

function App() {
  const [page, setPage] = useState<Page>("Home");
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [publicDashboard, setPublicDashboard] = useState<PublicDashboard | null>(null);
  const [dashboardUpdatedAt, setDashboardUpdatedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [token, setToken] = useState("");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loginPasswordVisible, setLoginPasswordVisible] = useState(false);
  const [registrationPasswordVisible, setRegistrationPasswordVisible] = useState(false);
  const [engineerPasswordVisible, setEngineerPasswordVisible] = useState(false);
  const [forgotPasswordOpen, setForgotPasswordOpen] = useState(false);
  const [emailVerificationStatus, setEmailVerificationStatus] = useState<
    "verifying" | "verified" | "error" | null
  >(null);
  const [passwordResetOpen, setPasswordResetOpen] = useState(false);
  const [passwordResetToken, setPasswordResetToken] = useState("");
  const [invitationAcceptOpen, setInvitationAcceptOpen] = useState(false);
  const [invitationToken, setInvitationToken] = useState("");
  const [googleScriptLoaded, setGoogleScriptLoaded] = useState(false);
  const googleButtonRef = useRef<HTMLDivElement>(null);
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim() ?? "";
  const [reportCoordinates, setReportCoordinates] = useState({ latitude: "", longitude: "" });
  const [reportLocationEvidence, setReportLocationEvidence] = useState<CapturedLocation | null>(null);
  const [apiOnline, setApiOnline] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const notificationsRef = useRef<HTMLDivElement>(null);
  const [readNotificationIds, setReadNotificationIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("All categories");
  const [reportOpen, setReportOpen] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [citizenRegistrationOpen, setCitizenRegistrationOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileData, setProfileData] = useState<ProfileData | null>(null);
  const [profileError, setProfileError] = useState("");
  const [adminAccounts, setAdminAccounts] = useState<AdminAccount[]>([]);
  const [adminAccountsError, setAdminAccountsError] = useState("");
  const [adminInvitationError, setAdminInvitationError] = useState("");
  const processedAuthLinks = useRef(new Set<string>());
  const [toast, setToast] = useState("");
  const [verificationQueue, setVerificationQueue] = useState<VerificationItem[]>([]);
  const [verificationQueueLoading, setVerificationQueueLoading] = useState(false);
  const [verificationQueueError, setVerificationQueueError] = useState("");
  const [selectedReview, setSelectedReview] = useState<VerificationItem | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [schemeDocuments, setSchemeDocuments] = useState<SchemeDocument[]>([]);
  const [schemeDocumentsError, setSchemeDocumentsError] = useState("");
  const [schemeDocumentsLoading, setSchemeDocumentsLoading] = useState(false);
  const [schemeTasks, setSchemeTasks] = useState<SchemeTask[]>([]);
  const [schemeTasksError, setSchemeTasksError] = useState("");
  const [schemeEligibleEngineers, setSchemeEligibleEngineers] = useState<EngineerOption[]>([]);
  const [schemeTaskDepartment, setSchemeTaskDepartment] = useState("Public Works");
  const [schemeTaskSkills, setSchemeTaskSkills] = useState("");
  const [schemeTaskEngineerId, setSchemeTaskEngineerId] = useState("");
  const [schemeTaskEligibilityLoading, setSchemeTaskEligibilityLoading] = useState(false);
  const [liveLocations, setLiveLocations] = useState<LiveWorkLocation[]>([]);
  const [liveLocationError, setLiveLocationError] = useState("");
  const [locationSharing, setLocationSharing] = useState<Set<string>>(new Set());
  const liveLocationWatches = useRef(new Map<string, LiveLocationWatch>());
  const [engineerRegistrationOpen, setEngineerRegistrationOpen] = useState(false);
  const [engineerApplications, setEngineerApplications] = useState<EngineerApplication[]>([]);
  const [eligibleEngineers, setEligibleEngineers] = useState<EngineerOption[]>([]);
  const [verificationOfficers, setVerificationOfficers] = useState<{ id: string; name: string }[]>([]);
  const [applicationReasons, setApplicationReasons] = useState<Record<string, string>>({});
  const [assignmentComplaintId, setAssignmentComplaintId] = useState("");
  const [assignmentEngineerId, setAssignmentEngineerId] = useState("");
  const [assignmentVerifierId, setAssignmentVerifierId] = useState("");
  const [assignmentEligibilityLoading, setAssignmentEligibilityLoading] = useState(false);
  const [eligibilityRefresh, setEligibilityRefresh] = useState(0);
  const [registrationStatus, setRegistrationStatus] = useState("");
  const [registrationProfile, setRegistrationProfile] = useState<EngineerRegistrationProfile | null>(null);
  const [registrationReviewReason, setRegistrationReviewReason] = useState("");
  const [selectedWorkComplaint, setSelectedWorkComplaint] = useState<Complaint | null>(null);
  const [workLocationEvidence, setWorkLocationEvidence] = useState<CapturedLocation | null>(null);
  const [workCoordinates, setWorkCoordinates] = useState({ latitude: "", longitude: "" });
  const [workEvidence, setWorkEvidence] = useState({ before: "", after: "" });
  const [evidenceProcessing, setEvidenceProcessing] = useState(0);
  const [historyComplaint, setHistoryComplaint] = useState<Complaint | null>(null);
  const [workHistory, setWorkHistory] = useState<WorkEvent[]>([]);
  const [complaintAttachments, setComplaintAttachments] = useState<ComplaintAttachment[]>([]);
  const [citizenFeedback, setCitizenFeedback] = useState<ComplaintFeedback | null>(null);
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);

  const refreshDashboard = useCallback(async (accessToken: string): Promise<boolean> => {
    try {
      const response = await fetch("/api/dashboard", {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!response.ok) throw new Error("Could not load your dashboard.");
      const payload = await response.json();
      if (!Array.isArray(payload.complaints)) throw new Error("Dashboard response did not include complaint records.");
      setComplaints(payload.complaints);
      setApiOnline(true);
      setDashboardUpdatedAt(new Date());
      return true;
    } catch {
      setApiOnline(false);
      return false;
    }
  }, []);

  const refreshPublicDashboard = useCallback(async (signal: AbortSignal) => {
    try {
      const response = await fetch("/api/public/dashboard", { signal });
      if (!response.ok) throw new Error("Could not load the public report dashboard.");
      const payload: PublicDashboard = await response.json();
      setPublicDashboard(payload);
      setComplaints(payload.complaints.map((report) => ({
        id: report.reference,
        reference: report.reference,
        title: report.title,
        description: "",
        category: report.category,
        severity: report.severity,
        official_status: report.official_status,
        engineer_work_status: report.engineer_work_status,
        verification_status: report.verification_status,
        ward: report.ward,
        address: report.ward,
        latitude: report.latitude,
        longitude: report.longitude,
        department: report.department,
        engineer_id: null,
        verifier_id: null,
      })));
      setApiOnline(true);
      setDashboardUpdatedAt(new Date());
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setApiOnline(false);
    }
  }, []);

  useEffect(() => {
    if (!token || user?.role === "admin") return;
    void refreshDashboard(token);
    const timer = window.setInterval(() => void refreshDashboard(token), 15_000);
    return () => window.clearInterval(timer);
  }, [token, user?.role, refreshDashboard]);

  useEffect(() => {
    if (token) return;
    const controller = new AbortController();
    void refreshPublicDashboard(controller.signal);
    const timer = window.setInterval(() => void refreshPublicDashboard(controller.signal), 15_000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [token, refreshPublicDashboard]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const parameters = new URLSearchParams(window.location.search);
    const verifyToken = parameters.get("verify_email");
    const resetToken = parameters.get("reset_password");
    const acceptToken = parameters.get("accept_invitation");
    if (verifyToken && !processedAuthLinks.current.has(`verify:${verifyToken}`)) {
      processedAuthLinks.current.add(`verify:${verifyToken}`);
      setEmailVerificationStatus("verifying");
      void fetch("/api/auth/verify-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: verifyToken }),
      })
        .then(async (response) => {
          const payload = await response.json().catch(() => null);
          if (!response.ok) throw new Error(payload?.detail ?? "Email verification failed.");
          setEmailVerificationStatus("verified");
        })
        .catch((error: unknown) => {
          setEmailVerificationStatus("error");
          setToast(error instanceof Error ? error.message : "Email verification failed.");
        });
      parameters.delete("verify_email");
    }
    if (resetToken) {
      setPasswordResetToken(resetToken);
      setPasswordResetOpen(true);
      parameters.delete("reset_password");
    }
    if (acceptToken) {
      setInvitationToken(acceptToken);
      setInvitationAcceptOpen(true);
      parameters.delete("accept_invitation");
    }
    if (verifyToken || resetToken || acceptToken) {
      const query = parameters.toString();
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
      );
    }
  }, []);

  useEffect(() => {
    if (!user) {
      setReadNotificationIds([]);
      return;
    }
    try {
      const saved = window.localStorage.getItem(`civicai:read-notifications:${user.id}`);
      const parsed: unknown = saved ? JSON.parse(saved) : [];
      if (!Array.isArray(parsed) || parsed.some((id) => typeof id !== "string")) {
        throw new Error("Saved notification state is invalid.");
      }
      setReadNotificationIds(parsed);
    } catch (error) {
      setReadNotificationIds([]);
      setToast(error instanceof Error ? error.message : "Saved notification status could not be loaded.");
    }
  }, [user?.id]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!notificationsOpen) return;
    function handleOutsideClick(event: MouseEvent) {
      if (!notificationsRef.current?.contains(event.target as Node)) {
        setNotificationsOpen(false);
      }
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setNotificationsOpen(false);
    }
    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [notificationsOpen]);

  useEffect(() => {
    if (!loginOpen) setLoginError("");
  }, [loginOpen]);

  useEffect(() => {
    if (!loginOpen || !googleClientId) return;
    if (window.google) {
      setGoogleScriptLoaded(true);
      return;
    }
    let script = document.querySelector<HTMLScriptElement>(
      'script[src="https://accounts.google.com/gsi/client"]',
    );
    const handleLoad = () => setGoogleScriptLoaded(true);
    const handleError = () => setLoginError("Google sign-in could not be loaded. Try again later.");
    if (!script) {
      script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", handleLoad);
    script.addEventListener("error", handleError);
    return () => {
      script?.removeEventListener("load", handleLoad);
      script?.removeEventListener("error", handleError);
    };
  }, [googleClientId, loginOpen]);

  useEffect(() => {
    if (!loginOpen || !googleClientId || !googleScriptLoaded || !googleButtonRef.current || !window.google) {
      return;
    }
    googleButtonRef.current.replaceChildren();
    window.google.accounts.id.initialize({
      client_id: googleClientId,
      callback: (response) => void signInWithGoogle(response.credential),
    });
    window.google.accounts.id.renderButton(googleButtonRef.current, {
      theme: "outline",
      size: "large",
      shape: "rectangular",
      text: "continue_with",
      width: Math.min(360, googleButtonRef.current.clientWidth || 320),
    });
    return () => googleButtonRef.current?.replaceChildren();
  }, [googleClientId, googleScriptLoaded, loginOpen]);

  useEffect(() => {
    if (page !== "Government schemes") return;
    const controller = new AbortController();
    setSchemeDocumentsLoading(true);
    setSchemeDocumentsError("");
    setSchemeDocuments([]);
    fetch("/api/assistant/documents", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Approved scheme documents could not be loaded.");
        const documents: SchemeDocument[] = await response.json();
        setSchemeDocuments(documents);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSchemeDocumentsError(
          error instanceof Error ? error.message : "Approved scheme documents could not be loaded.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setSchemeDocumentsLoading(false);
      });
    return () => controller.abort();
  }, [page]);

  useEffect(() => {
    if (page !== "Government schemes") return;
    const controller = new AbortController();
    setSchemeTasksError("");
    fetch("/api/public/scheme-tasks", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Scheme-linked work could not be loaded.");
        setSchemeTasks(await response.json());
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSchemeTasksError(
          error instanceof Error ? error.message : "Scheme-linked work could not be loaded.",
        );
      });
    return () => controller.abort();
  }, [page]);

  useEffect(() => {
    if (!token || user?.role !== "verifier") {
      setVerificationQueue([]);
      setVerificationQueueLoading(false);
      setVerificationQueueError("");
      return;
    }
    const controller = new AbortController();
    async function refreshVerificationQueue() {
      setVerificationQueueLoading(true);
      try {
        const response = await fetch("/api/verification/queue", {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Could not load the verification queue.");
        setVerificationQueue(await response.json());
        setVerificationQueueError("");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setVerificationQueueError(
          error instanceof Error ? error.message : "The verification queue is unavailable.",
        );
      } finally {
        if (!controller.signal.aborted) setVerificationQueueLoading(false);
      }
    }
    void refreshVerificationQueue();
    const timer = window.setInterval(() => void refreshVerificationQueue(), 15_000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [token, user?.role]);

  useEffect(() => {
    if (page !== "Work tracking" || !token || !user) return;
    const controller = new AbortController();
    const headers = { Authorization: `Bearer ${token}` };
    async function loadWorkflow() {
      try {
        if (user?.role === "officer") {
          const responses = await Promise.all([
            fetch("/api/engineers/registrations", { headers, signal: controller.signal }),
            fetch("/api/verification/officers", { headers, signal: controller.signal }),
            fetch("/api/scheme-tasks", { headers, signal: controller.signal }),
          ]);
          if (responses.some((response) => !response.ok)) {
            throw new Error("Could not load the officer work queue.");
          }
          const applications: EngineerApplication[] = await responses[0].json();
          const officers: { id: string; name: string }[] = await responses[1].json();
          const tasks: SchemeTask[] = await responses[2].json();
          setEngineerApplications(applications);
          setVerificationOfficers(officers);
          setSchemeTasks(tasks);
          setAssignmentVerifierId((current) =>
            officers.some((officer) => officer.id === current) ? current : officers[0]?.id ?? "",
          );
        } else if (user?.role === "engineer" || user?.role === "engineer_pending") {
          const [profileResponse, tasksResponse] = await Promise.all([
            fetch("/api/engineers/me/registration", { headers, signal: controller.signal }),
            user.role === "engineer"
              ? fetch("/api/scheme-tasks", { headers, signal: controller.signal })
              : Promise.resolve(null),
          ]);
          if (!profileResponse.ok) throw new Error("Could not load your engineer application.");
          const profile: EngineerRegistrationProfile = await profileResponse.json();
          setRegistrationStatus(profile.registration_status);
          setRegistrationProfile(profile);
          setRegistrationReviewReason(profile.reviews[profile.reviews.length - 1]?.reason ?? "");
          if (profile.registration_status === "APPROVED" && user.role === "engineer_pending") {
            setUser((current) =>
              current?.id === user.id ? { ...current, role: "engineer" } : current,
            );
          }
          if (tasksResponse) {
            if (!tasksResponse.ok) throw new Error("Could not load your assigned scheme work.");
            setSchemeTasks(await tasksResponse.json());
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setToast(error instanceof Error ? error.message : "The work queue is unavailable.");
      }
    }
    void loadWorkflow();
    const timer = window.setInterval(() => void loadWorkflow(), 15_000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [page, token, user?.id, user?.role]);

  useEffect(() => {
    if (!token || user?.role !== "admin") {
      setAdminAccounts([]);
      setAdminAccountsError("");
      return;
    }
    const controller = new AbortController();
    async function refreshAccounts() {
      try {
        const response = await fetch("/api/admin/users", {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail ?? "Could not load user accounts.");
        setAdminAccounts(payload);
        setAdminAccountsError("");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setAdminAccountsError(error instanceof Error ? error.message : "Could not load user accounts.");
      }
    }
    void refreshAccounts();
    const timer = window.setInterval(() => void refreshAccounts(), 15_000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [token, user?.role]);

  useEffect(() => {
    if (!profileOpen || !token) return;
    const controller = new AbortController();
    void fetch("/api/profile", {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail ?? "Could not load your profile.");
        setProfileData(payload);
        setProfileError("");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setProfileError(error instanceof Error ? error.message : "Could not load your profile.");
      });
    return () => controller.abort();
  }, [profileOpen, token]);

  useEffect(() => {
    if (page !== "Work tracking" || user?.role !== "officer") return;
    const assignable = complaints.filter(
      (item) =>
        !["CLOSED", "OFFICIALLY_COMPLETED"].includes(item.official_status) &&
        item.verification_status !== "PENDING_REVIEW",
    );
    setAssignmentComplaintId((current) =>
      assignable.some((item) => item.id === current) ? current : assignable[0]?.id ?? "",
    );
  }, [complaints, page, user?.role]);

  useEffect(() => {
    if (page !== "Work tracking" || user?.role !== "officer") return;
    const timer = window.setInterval(() => {
      setEligibilityRefresh((current) => current + 1);
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [page, user?.role]);

  useEffect(() => {
    if (page !== "Work tracking" || !token || user?.role !== "officer" || !assignmentComplaintId) {
      setEligibleEngineers([]);
      setAssignmentEngineerId("");
      setAssignmentEligibilityLoading(false);
      return;
    }
    const controller = new AbortController();
    setEligibleEngineers([]);
    setAssignmentEngineerId("");
    setAssignmentEligibilityLoading(true);
    fetch(`/api/complaints/${assignmentComplaintId}/eligible-engineers`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const payload = await response.json();
          throw new Error(payload.detail ?? "Eligible engineers could not be loaded.");
        }
        const engineers: EngineerOption[] = await response.json();
        setEligibleEngineers(engineers);
        setAssignmentEngineerId((current) =>
          engineers.some((engineer) => engineer.id === current)
            ? current
            : engineers[0]?.id ?? "",
        );
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setEligibleEngineers([]);
        setAssignmentEngineerId("");
        setToast(error instanceof Error ? error.message : "Eligible engineers could not be loaded.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setAssignmentEligibilityLoading(false);
      });
    return () => controller.abort();
  }, [assignmentComplaintId, eligibilityRefresh, page, token, user?.role]);

  useEffect(() => {
    if (
      page !== "Work tracking" ||
      !token ||
      user?.role !== "officer" ||
      !schemeTaskDepartment.trim() ||
      !schemeTaskSkills.trim()
    ) {
      setSchemeEligibleEngineers([]);
      setSchemeTaskEngineerId("");
      setSchemeTaskEligibilityLoading(false);
      return;
    }
    const controller = new AbortController();
    setSchemeEligibleEngineers([]);
    setSchemeTaskEngineerId("");
    setSchemeTaskEligibilityLoading(true);
    const parameters = new URLSearchParams({
      department: schemeTaskDepartment.trim(),
      required_skills: schemeTaskSkills.trim(),
    });
    fetch(`/api/scheme-tasks/eligible-engineers?${parameters}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const payload = await response.json();
          throw new Error(payload.detail ?? "Scheme-task eligibility could not be checked.");
        }
        const engineers: EngineerOption[] = await response.json();
        setSchemeEligibleEngineers(engineers);
        setSchemeTaskEngineerId((current) =>
          engineers.some((engineer) => engineer.id === current)
            ? current
            : engineers[0]?.id ?? "",
        );
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSchemeEligibleEngineers([]);
        setSchemeTaskEngineerId("");
        setToast(error instanceof Error ? error.message : "Scheme-task eligibility could not be checked.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setSchemeTaskEligibilityLoading(false);
      });
    return () => controller.abort();
  }, [page, schemeTaskDepartment, schemeTaskSkills, token, user?.role]);

  useEffect(() => {
    if (page !== "Work tracking" || !token || user?.role !== "officer") {
      setLiveLocations([]);
      setLiveLocationError("");
      return;
    }
    const controller = new AbortController();
    async function refreshLiveLocations() {
      try {
        const response = await fetch("/api/work/live-locations", {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok) {
          const payload = await response.json();
          throw new Error(payload.detail ?? "Live work locations could not be loaded.");
        }
        setLiveLocations(await response.json());
        setLiveLocationError("");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setLiveLocationError(
          error instanceof Error ? error.message : "Live work locations could not be loaded.",
        );
      }
    }
    void refreshLiveLocations();
    const timer = window.setInterval(() => void refreshLiveLocations(), 15000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [page, token, user?.role]);

  useEffect(() => {
    return () => {
      for (const [key, watcher] of liveLocationWatches.current) {
        navigator.geolocation?.clearWatch(watcher.watchId);
        void fetch(watcher.path, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        })
          .then((response) => {
            if (!response.ok) throw new Error("The server could not immediately clear this location.");
          })
          .catch((error: unknown) => {
            setToast(
              error instanceof Error
                ? `${error.message} Stored coordinates expire from the live view after 90 seconds.`
                : "Location sharing could not be stopped immediately; coordinates expire from the live view after 90 seconds.",
            );
        });
        liveLocationWatches.current.delete(key);
      }
      setLocationSharing(new Set());
    };
  }, [page, token, user?.id]);

  const filteredComplaints = useMemo(() => {
    const query = search.trim().toLowerCase();
    return complaints.filter((complaint) => {
      const matchesQuery =
        !query ||
        [complaint.reference, complaint.title, complaint.address, complaint.ward]
          .join(" ")
          .toLowerCase()
          .includes(query);
      const matchesCategory =
        categoryFilter === "All categories" || complaint.category === categoryFilter;
      return matchesQuery && matchesCategory;
    });
  }, [categoryFilter, complaints, search]);

  const counts = useMemo(() => {
    if (!user && publicDashboard) {
      return {
        total: publicDashboard.counts.total_reports,
        open: publicDashboard.counts.open,
        verification: publicDashboard.counts.awaiting_verification,
        urgent: publicDashboard.counts.high_priority,
        resolved: publicDashboard.counts.resolved,
      };
    }
    const active = complaints.filter(
      (item) => !["CLOSED", "OFFICIALLY_COMPLETED"].includes(item.official_status),
    );
    return {
      total: complaints.length,
      open: active.length,
      verification: complaints.filter((item) => item.verification_status === "PENDING_REVIEW").length,
      urgent: active.filter((item) => ["Critical", "High"].includes(item.severity)).length,
      resolved: complaints.filter((item) =>
        ["CLOSED", "OFFICIALLY_COMPLETED"].includes(item.official_status),
      ).length,
    };
  }, [complaints, publicDashboard, user]);

  const notifications = useMemo<WorkspaceNotification[]>(() => {
    if (!user) return [];
    if (user.role === "admin") return [];
    if (user.role === "citizen") {
      return complaints.slice(0, 6).map((complaint) => ({
        id: `${complaint.id}:citizen:${complaint.official_status}`,
        title: `Report ${complaint.reference}`,
        detail: `Current status: ${statusLabel(complaint.official_status)}.`,
        page: "Reports",
      }));
    }
    if (user.role === "engineer") {
      return complaints
        .filter((complaint) =>
          complaint.engineer_work_status === "NOT_STARTED" ||
          complaint.verification_status === "REWORK_REQUIRED",
        )
        .slice(0, 8)
        .map((complaint) => ({
          id: `${complaint.id}:engineer:${complaint.engineer_work_status}:${complaint.verification_status}`,
          title: complaint.verification_status === "REWORK_REQUIRED"
            ? `Correction requested: ${complaint.reference}`
            : `New assignment: ${complaint.reference}`,
          detail: complaint.title,
          page: "Work tracking",
        }));
    }
    if (user.role === "verifier") {
      return verificationQueue.slice(0, 8).map((item) => ({
        id: item.submission.id,
        title: `Review submission: ${item.complaint.reference}`,
        detail: item.complaint.title,
        page: "Work tracking",
      }));
    }
    if (user.role === "engineer_pending") {
      if (!registrationStatus) return [];
      return [{
        id: `engineer-registration:${registrationStatus}`,
        title: `Engineer registration: ${statusLabel(registrationStatus)}`,
        detail: registrationReviewReason || "View your application in work tracking.",
        page: "Work tracking",
      }];
    }
    return complaints
      .filter((complaint) =>
        (complaint.engineer_id == null &&
          !["CLOSED", "OFFICIALLY_COMPLETED"].includes(complaint.official_status)) ||
        complaint.verification_status === "PENDING_REVIEW",
      )
      .slice(0, 8)
      .map((complaint) => ({
        id: `${complaint.id}:officer:${complaint.engineer_id ? "verification" : "assignment"}:${complaint.verification_status}`,
        title: complaint.verification_status === "PENDING_REVIEW"
          ? `Verification pending: ${complaint.reference}`
          : `Assignment needed: ${complaint.reference}`,
        detail: complaint.title,
        page: "Work tracking",
      }));
  }, [complaints, registrationReviewReason, registrationStatus, user, verificationQueue]);
  const unreadNotifications = notifications.filter(
    (notification) => !readNotificationIds.includes(notification.id),
  );

  async function completeSignIn(payload: AuthResponse) {
    setComplaints([]);
    setToken(payload.access_token);
    setUser(payload.user);
    setPage("Home");
    setApiOnline(true);
    const dashboardLoaded = payload.user.role === "admin"
      ? true
      : await refreshDashboard(payload.access_token);
    setLoginOpen(false);
    setToast(
      dashboardLoaded
        ? `Welcome back, ${payload.user.name.split(" ")[0]}.`
        : "Signed in, but your dashboard could not be loaded. Try again shortly.",
    );
  }

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginError("");
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail ?? "Sign-in failed.");
      }
      const payload: AuthResponse = await response.json();
      await completeSignIn(payload);
    } catch (error) {
      setLoginError(
        error instanceof TypeError
          ? "Unable to reach the NagarikSetu service. Start the API and try again."
          : error instanceof Error
            ? error.message
            : "The NagarikSetu service is unavailable.",
      );
    }
  }

  async function signInWithGoogle(credential: string) {
    setLoginError("");
    try {
      const response = await fetch("/api/auth/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Google sign-in failed.");
      await completeSignIn(payload);
    } catch (error) {
      setLoginError(
        error instanceof TypeError
          ? "Unable to reach the NagarikSetu service. Start the API and try again."
          : error instanceof Error
            ? error.message
            : "Google sign-in failed.",
      );
    }
  }

  async function registerCitizen(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.get("name"),
          email: form.get("email"),
          password: form.get("password"),
          confirm_password: form.get("confirm_password"),
          phone_number: form.get("phone_number"),
          terms_accepted: form.get("terms_accepted") === "on",
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(payload?.detail ?? "Your NagarikSetu account could not be created.");
      }
      setLoginEmail(String(form.get("email") ?? ""));
      setLoginPassword("");
      setCitizenRegistrationOpen(false);
      setLoginOpen(true);
      setToast("Account created. Check your email and verify it before signing in.");
    } catch (error) {
      setToast(
        error instanceof TypeError
          ? "Unable to reach the NagarikSetu service. Start the API and try again."
          : error instanceof Error
            ? error.message
            : "Your NagarikSetu account could not be created.",
      );
    }
  }

  async function useCurrentLocationForReport() {
    try {
      const location = await requestCurrentLocation();
      setReportCoordinates({
        latitude: location.latitude.toFixed(6),
        longitude: location.longitude.toFixed(6),
      });
      setReportLocationEvidence(location);
      setToast("Current location added to the report.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not get your location.");
    }
  }

  async function useCurrentLocationForWork() {
    try {
      const location = await requestCurrentLocation();
      setWorkLocationEvidence(location);
      setWorkCoordinates({
        latitude: location.latitude.toFixed(6),
        longitude: location.longitude.toFixed(6),
      });
      setToast(`Work location captured with ±${Math.round(location.accuracy)} m reported accuracy.`);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not get your location.");
    }
  }

  async function selectWorkEvidence(which: "before" | "after", file?: File) {
    if (!file) return;
    setEvidenceProcessing((count) => count + 1);
    try {
      const image = await compressEvidenceImage(file);
      setWorkEvidence((current) => ({ ...current, [which]: image }));
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The selected photo could not be processed.");
    } finally {
      setEvidenceProcessing((count) => Math.max(0, count - 1));
    }
  }

  function openWorkSubmission(complaint: Complaint) {
    setWorkEvidence({ before: "", after: "" });
    setWorkLocationEvidence(null);
    setWorkCoordinates({
      latitude: String(complaint.latitude),
      longitude: String(complaint.longitude),
    });
    setSelectedWorkComplaint(complaint);
  }

  function signOut() {
    const accessToken = token;
    setToken("");
    setUser(null);
    setPage("Home");
    setToast("Signed out. Public report data remains available.");
    void fetch("/api/auth/logout", {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((response) => {
        if (!response.ok) {
          setToast("Signed out on this device, but server logout could not be confirmed.");
        }
      })
      .catch(() => {
        setToast("Signed out on this device. Server logout could not be reached.");
      });
  }

  async function resendVerificationEmail() {
    if (!loginEmail.trim()) {
      setLoginError("Enter your email address first.");
      return;
    }
    try {
      const response = await fetch("/api/auth/resend-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: loginEmail }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not resend the verification email.");
      setToast(payload.message);
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Could not resend the verification email.");
    }
  }

  async function requestPasswordReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email") }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not request a password reset.");
      setForgotPasswordOpen(false);
      setToast(payload.message);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not request a password reset.");
    }
  }

  async function resetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: passwordResetToken,
          password: form.get("password"),
          confirm_password: form.get("confirm_password"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not reset the password.");
      setPasswordResetOpen(false);
      setPasswordResetToken("");
      setLoginOpen(true);
      setToast(payload.message);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not reset the password.");
    }
  }

  async function acceptOfficialInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/auth/accept-invitation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: invitationToken,
          password: form.get("password"),
          confirm_password: form.get("confirm_password"),
          phone_number: form.get("phone_number"),
          terms_accepted: form.get("terms_accepted") === "on",
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not activate this official account.");
      setInvitationAcceptOpen(false);
      setInvitationToken("");
      setLoginOpen(true);
      setToast(payload.message);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not activate this official account.");
    }
  }

  async function createOfficialInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setAdminInvitationError("");
    try {
      const response = await fetch("/api/admin/invitations", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: form.get("name"),
          email: form.get("email"),
          role: form.get("role"),
          employee_id: form.get("employee_id"),
          designation: form.get("designation"),
          department: form.get("department"),
          jurisdiction: form.get("jurisdiction"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not send this invitation.");
      formElement.reset();
      setToast(payload.message);
    } catch (error) {
      setAdminInvitationError(error instanceof Error ? error.message : "Could not send this invitation.");
    }
  }

  async function changeAccountStatus(account: AdminAccount) {
    try {
      const response = await fetch(`/api/admin/users/${account.id}/status`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ active: account.account_status !== "ACTIVE" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not update this account.");
      setAdminAccounts((current) =>
        current.map((item) =>
          item.id === account.id ? { ...item, account_status: payload.account_status } : item,
        ),
      );
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not update this account.");
    }
  }

  async function updateProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profileData) return;
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/profile", {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: form.get("name"),
          phone_number: form.get("phone_number"),
          address: form.get("address"),
          ward: form.get("ward"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not update your profile.");
      setProfileData((current) =>
        current ? {
          ...current,
          name: payload.name,
          phone_number: payload.phone_number,
          address: payload.address,
          ward: payload.ward,
        } : current,
      );
      setUser((current) => current ? { ...current, name: payload.name } : current);
      setToast("Profile updated.");
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : "Could not update your profile.");
    }
  }

  async function submitReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      setReportOpen(false);
      setLoginOpen(true);
      setToast("Sign in to submit a report to the API.");
      return;
    }
    const form = new FormData(event.currentTarget);
    if (reportLocationEvidence) {
      form.set("location_accuracy_meters", String(reportLocationEvidence.accuracy));
      form.set("location_captured_at", reportLocationEvidence.capturedAt);
    } else {
      form.delete("location_accuracy_meters");
      form.delete("location_captured_at");
    }
    const attachments = form.getAll("files").filter(
      (entry): entry is File => entry instanceof File && entry.name.length > 0,
    );
    if (attachments.length > 5) {
      setToast("Attach no more than 5 files to a report.");
      return;
    }
    if (attachments.some((file) => file.size > 20 * 1024 * 1024)) {
      setToast("Each report attachment must be 20 MB or smaller.");
      return;
    }
    if (attachments.reduce((total, file) => total + file.size, 0) > 60 * 1024 * 1024) {
      setToast("Report attachments must total 60 MB or less.");
      return;
    }
    try {
      const response = await fetch("/api/complaints/with-evidence", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail ?? "The report could not be submitted.");
      }
      const created: Complaint = await response.json();
      setComplaints((existing) => [created, ...existing]);
      setReportOpen(false);
      const assessment = created.assessment;
      const triageNotice = assessment
        ? ` Preliminary triage suggests ${assessment.suggested_severity} priority for ${assessment.suggested_category} (${assessment.suggested_department}).`
        : "";
      const duplicateNotice = assessment?.duplicate_references.length
        ? ` Possible related reports: ${assessment.duplicate_references.join(", ")}.`
        : "";
      setToast(`Report ${created.reference} submitted with ${attachments.length} attachment(s).${triageNotice}${duplicateNotice}`);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The NagarikSetu service is unavailable.");
    }
  }

  async function sendQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = chatQuestion.trim();
    if (!question) return;
    if (!token) {
      setLoginOpen(true);
      setToast("Sign in to chat with NagarikSetu Guide.");
      return;
    }
    setChatMessages((current) => [...current, { role: "user", content: question }]);
    setChatQuestion("");
    setChatLoading(true);
    try {
      const response = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question, language: "English" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The assistant is unavailable.");
      setChatMessages((current) => [
        ...current,
        { role: "assistant", content: payload.answer, sources: payload.sources },
      ]);
    } catch (error) {
      setChatMessages((current) => [
        ...current,
        {
          role: "assistant",
          content:
            error instanceof Error
              ? error.message
              : "The assistant is unavailable. Please try again.",
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  }

  async function decideReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedReview || !token) return;
    const form = new FormData(event.currentTarget);
    const decision = String(form.get("decision"));
    const reason = String(form.get("reason") ?? "");
    try {
      const response = await fetch(
        `/api/verification/${selectedReview.submission.id}/decision`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ decision, reason }),
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The decision was not recorded.");
      setVerificationQueue((current) =>
        current.filter((item) => item.submission.id !== selectedReview.submission.id),
      );
      setComplaints((current) =>
        current.map((item) =>
          item.id === payload.complaint_id
            ? {
                ...item,
                official_status: payload.official_status,
                engineer_work_status: payload.engineer_work_status,
                verification_status: payload.verification_status,
              }
            : item,
        ),
      );
      setSelectedReview(null);
      setToast(decision === "APPROVED" ? "Work verified and officially completed." : "Rework requested.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The decision was not recorded.");
    }
  }

  async function submitEngineerRegistration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const skills = String(form.get("skills") ?? "")
      .split(",")
      .map((skill) => skill.trim())
      .filter(Boolean);
    try {
      const response = await fetch("/api/engineers/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.get("name"),
          email: form.get("email"),
          password: form.get("password"),
          confirm_password: form.get("confirm_password"),
          phone_number: form.get("phone_number"),
          terms_accepted: form.get("terms_accepted") === "on",
          department: form.get("department"),
          registration_number: form.get("registration_number"),
          skills,
          application_note: form.get("application_note"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The application could not be submitted.");
      setEngineerRegistrationOpen(false);
      setLoginEmail(String(form.get("email") ?? ""));
      setLoginPassword("");
      setToast("Application submitted. Verify your email before an officer can review it.");
      setLoginOpen(true);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The application could not be submitted.");
    }
  }

  async function reviewEngineerApplication(
    application: EngineerApplication,
    decision: "APPROVED" | "REJECTED",
  ) {
    const reason = applicationReasons[application.user_id]?.trim() ?? "";
    if (reason.length < 8) {
      setToast("Enter an approval or rejection reason of at least 8 characters.");
      return;
    }
    try {
      const response = await fetch(
        `/api/engineers/registrations/${application.user_id}/decision`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ decision, reason }),
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The application decision was not recorded.");
      setEngineerApplications((current) =>
        current.filter((item) => item.user_id !== application.user_id),
      );
      if (decision === "APPROVED") {
        setEligibilityRefresh((current) => current + 1);
      }
      setToast(decision === "APPROVED" ? "Engineer registration approved." : "Application rejected with a recorded reason.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The application decision was not recorded.");
    }
  }

  async function resubmitEngineerRegistration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const skills = String(form.get("skills") ?? "")
      .split(",")
      .map((skill) => skill.trim())
      .filter(Boolean);
    try {
      const response = await fetch("/api/engineers/me/registration", {
        method: "PUT",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          department: form.get("department"),
          registration_number: form.get("registration_number"),
          skills,
          application_note: form.get("application_note"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The application could not be resubmitted.");
      setRegistrationStatus(payload.registration_status);
      setRegistrationReviewReason("");
      setToast("Updated application resubmitted for officer review.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The application could not be resubmitted.");
    }
  }

  async function assignWork(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const complaintId = String(form.get("complaint_id") ?? "");
    try {
      const response = await fetch(`/api/complaints/${complaintId}/assign`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          engineer_id: assignmentEngineerId,
          verifier_id: assignmentVerifierId,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The assignment could not be saved.");
      setComplaints((current) =>
        current.map((item) => (item.id === complaintId ? payload : item)),
      );
      setToast("Engineer and independent verification officer assigned.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The assignment could not be saved.");
    }
  }

  async function createSchemeTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const requiredSkills = String(form.get("required_skills") ?? "")
      .split(",")
      .map((skill) => skill.trim())
      .filter(Boolean);
    try {
      const response = await fetch("/api/scheme-tasks", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          scheme_title: form.get("scheme_title"),
          title: form.get("title"),
          description: form.get("description"),
          department: schemeTaskDepartment,
          required_skills: requiredSkills,
          engineer_id: schemeTaskEngineerId,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Scheme work could not be assigned.");
      setSchemeTasks((current) => [payload, ...current]);
      setSchemeTaskSkills("");
      setToast(`Scheme work assigned to ${payload.assigned_engineer?.name ?? "the selected engineer"}.`);
      formElement.reset();
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Scheme work could not be assigned.");
    }
  }

  async function updateSchemeTask(
    task: SchemeTask,
    action: "start" | "progress" | "complete",
    body?: { note: string },
  ) {
    try {
      const response = await fetch(`/api/scheme-tasks/${task.id}/${action}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Scheme work could not be updated.");
      setSchemeTasks((current) =>
        current.map((item) => (item.id === task.id ? payload : item)),
      );
      if (action === "complete") {
        stopLiveLocationTracking(`scheme:${task.id}`, false);
      }
      setToast(
        action === "start"
          ? "Scheme work started."
          : action === "complete"
            ? "Scheme work marked complete."
            : "Scheme work progress saved.",
      );
      return true;
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Scheme work could not be updated.");
      return false;
    }
  }

  async function reviewTriage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignmentComplaintId) return;
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(`/api/complaints/${assignmentComplaintId}/triage`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          category: form.get("category"),
          severity: form.get("severity"),
          reason: form.get("reason"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The triage review could not be saved.");
      setComplaints((current) =>
        current.map((item) => (item.id === assignmentComplaintId ? payload : item)),
      );
      setEligibilityRefresh((value) => value + 1);
      setToast("Officer triage was recorded. Engineer eligibility has been refreshed.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The triage review could not be saved.");
    }
  }

  async function startWork(complaint: Complaint) {
    try {
      const response = await fetch(`/api/complaints/${complaint.id}/work/start`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          note:
            complaint.engineer_work_status === "REWORK_IN_PROGRESS"
              ? "Engineer resumed work after the officer requested rework."
              : "Engineer started the assigned field work.",
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Work could not be started.");
      setComplaints((current) =>
        current.map((item) =>
          item.id === complaint.id
            ? {
                ...item,
                engineer_work_status: payload.engineer_work_status,
                official_status: "IN_PROGRESS",
              }
            : item,
        ),
      );
      setToast("Work start recorded.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Work could not be started.");
    }
  }

  function startLiveLocationTracking(key: string, path: string) {
    if (!token || !navigator.geolocation) {
      setToast("Live location requires a supported browser and an active sign-in.");
      return;
    }
    if (liveLocationWatches.current.has(key)) return;
    const accepted = window.confirm(
      "Share your live location with government officers while this work is active? Location sharing can be stopped at any time.",
    );
    if (!accepted) return;
    const watcher: LiveLocationWatch = {
      watchId: 0,
      lastPosition: null,
      lastSentAt: 0,
      path,
    };
    const uploadLocation = () => {
      if (!watcher.lastPosition || Date.now() - watcher.lastSentAt < 30_000) return;
      watcher.lastSentAt = Date.now();
      void fetch(path, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude: watcher.lastPosition.coords.latitude,
          longitude: watcher.lastPosition.coords.longitude,
        }),
      })
        .then(async (response) => {
          const payload = await response.json().catch(() => null);
          if (!response.ok) throw new Error(payload?.detail ?? "Live location could not be shared.");
        })
        .catch((error: unknown) => {
          stopLiveLocationTracking(key, false);
          setToast(error instanceof Error ? error.message : "Live location could not be shared.");
        });
    };
    liveLocationWatches.current.set(key, watcher);
    watcher.watchId = navigator.geolocation.watchPosition(
      (position) => {
        watcher.lastPosition = position;
        uploadLocation();
      },
      (error) => {
        stopLiveLocationTracking(key, false);
        setToast(`Live location stopped: ${error.message}`);
      },
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 },
    );
    setLocationSharing((current) => new Set(current).add(key));
    setToast("Location sharing is on. Only government officers can view your live location.");
  }

  function stopLiveLocationTracking(key: string, showConfirmation = true) {
    const watcher = liveLocationWatches.current.get(key);
    if (!watcher) return;
    navigator.geolocation?.clearWatch(watcher.watchId);
    liveLocationWatches.current.delete(key);
    setLocationSharing((current) => {
      const next = new Set(current);
      next.delete(key);
      return next;
    });
    void fetch(watcher.path, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (response) => {
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Location sharing could not be stopped on the server.");
        }
        if (showConfirmation) setToast("Live location sharing stopped.");
      })
      .catch((error: unknown) => {
        setToast(
          error instanceof Error
            ? error.message
            : "Location sharing could not be stopped on the server; stored coordinates expire after 90 seconds.",
        );
      });
  }

  async function updateWorkProgress(event: FormEvent<HTMLFormElement>, complaint: Complaint) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(`/api/complaints/${complaint.id}/work/progress`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ note: form.get("note") }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Progress could not be recorded.");
      event.currentTarget.reset();
      setToast("Progress update saved to the work history.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Progress could not be recorded.");
    }
  }

  async function submitWork(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkComplaint) return;
    if (!workEvidence.before || !workEvidence.after) {
      setToast("Add both a before photo and an after photo to submit completed work.");
      return;
    }
    const form = new FormData(event.currentTarget);
    const capturedAt = String(form.get("captured_at") ?? "");
    try {
      const response = await fetch(
        `/api/complaints/${selectedWorkComplaint.id}/work/submit`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            work_details: form.get("work_details"),
            completion_notes: form.get("completion_notes"),
            before_evidence: workEvidence.before,
            after_evidence: workEvidence.after,
            latitude: Number(form.get("latitude")),
            longitude: Number(form.get("longitude")),
            captured_at: new Date(capturedAt).toISOString(),
            location_accuracy_meters: workLocationEvidence?.accuracy ?? null,
            location_captured_at: workLocationEvidence?.capturedAt ?? null,
          }),
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Work could not be submitted.");
      stopLiveLocationTracking(`complaint:${selectedWorkComplaint.id}`, false);
      setSelectedWorkComplaint(null);
      setComplaints((current) =>
        current.map((item) =>
          item.id === selectedWorkComplaint.id
            ? {
                ...item,
                engineer_work_status: "SUBMITTED_FOR_VERIFICATION",
                verification_status: "PENDING_REVIEW",
                official_status: "AWAITING_VERIFICATION",
              }
            : item,
        ),
      );
      setToast(`Work submitted for independent review (attempt ${payload.attempt_number}).`);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Work could not be submitted.");
    }
  }

  async function showWorkHistory(complaint: Complaint) {
    if (!token) {
      setLoginOpen(true);
      setToast("Sign in to view the verified work timeline.");
      return;
    }
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [historyResponse, attachmentsResponse] = await Promise.all([
        fetch(`/api/complaints/${complaint.id}/work/history`, { headers }),
        fetch(`/api/complaints/${complaint.id}/attachments`, { headers }),
      ]);
      const payload = await historyResponse.json();
      if (!historyResponse.ok) throw new Error(payload.detail ?? "The work history is unavailable.");
      const attachments = await attachmentsResponse.json();
      if (!attachmentsResponse.ok) throw new Error(attachments.detail ?? "Report attachments could not be loaded.");
      setWorkHistory(payload);
      setComplaintAttachments(attachments);
      setCitizenFeedback(null);
      if (user?.role === "citizen" && ["CLOSED", "OFFICIALLY_COMPLETED"].includes(complaint.official_status)) {
        const feedbackResponse = await fetch(
          `/api/complaints/${complaint.id}/feedback`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        if (feedbackResponse.ok) {
          setCitizenFeedback(await feedbackResponse.json());
        } else if (feedbackResponse.status !== 404) {
          const feedbackError = await feedbackResponse.json();
          throw new Error(feedbackError.detail ?? "Citizen feedback could not be loaded.");
        }
      }
      setHistoryComplaint(complaint);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The work history is unavailable.");
    }
  }

  async function downloadComplaintAttachment(attachment: ComplaintAttachment) {
    if (!token) return;
    try {
      const response = await fetch(`/api/complaint-attachments/${attachment.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.detail ?? "The attachment could not be downloaded.");
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = attachment.original_name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "The attachment could not be downloaded.");
    }
  }

  async function submitFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !historyComplaint) return;
    const form = new FormData(event.currentTarget);
    setFeedbackSubmitting(true);
    try {
      const response = await fetch(`/api/complaints/${historyComplaint.id}/feedback`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          rating: Number(form.get("rating")),
          comment: String(form.get("comment") ?? ""),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Feedback could not be submitted.");
      setCitizenFeedback(payload);
      setToast("Thank you. Your closure feedback has been recorded.");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Feedback could not be submitted.");
    } finally {
      setFeedbackSubmitting(false);
    }
  }

  function changePage(nextPage: Page) {
    if (nextPage === "Work tracking" && (user?.role === "citizen" || user?.role === "admin")) {
      setToast("Work tracking is available to engineers and authorized staff.");
      setMobileNav(false);
      return;
    }
    setPage(nextPage);
    setMobileNav(false);
    setNotificationsOpen(false);
  }

  function toggleNotifications() {
    const opening = !notificationsOpen;
    if (opening && user && unreadNotifications.length > 0) {
      const readIds = [
        ...new Set([
          ...readNotificationIds,
          ...unreadNotifications.map((notification) => notification.id),
        ]),
      ];
      setReadNotificationIds(readIds);
      try {
        window.localStorage.setItem(
          `civicai:read-notifications:${user.id}`,
          JSON.stringify(readIds),
        );
      } catch {
        setToast("Updates were marked as read for this visit but could not be saved.");
      }
    }
    setNotificationsOpen(opening);
  }

  const activeQueue = complaints.filter(
    (item) => item.official_status !== "OFFICIALLY_COMPLETED" && item.official_status !== "CLOSED",
  );
  const engineerDashboardMetrics = {
    assigned: complaints.length,
    newAssignments: complaints.filter((item) => item.engineer_work_status === "NOT_STARTED").length,
    inProgress: complaints.filter((item) =>
      ["IN_PROGRESS", "REWORK_IN_PROGRESS"].includes(item.engineer_work_status),
    ).length,
    awaitingReview: complaints.filter((item) => item.verification_status === "PENDING_REVIEW").length,
    rework: complaints.filter((item) => item.verification_status === "REWORK_REQUIRED").length,
    approved: complaints.filter((item) => item.verification_status === "APPROVED").length,
  };
  const officerDashboardMetrics = {
    assigned: complaints.filter((item) => item.engineer_id != null).length,
    pendingAssignment: complaints.filter((item) =>
      item.engineer_id == null && !["CLOSED", "OFFICIALLY_COMPLETED"].includes(item.official_status),
    ).length,
    awaitingReview: complaints.filter((item) => item.verification_status === "PENDING_REVIEW").length,
    approved: complaints.filter((item) => item.verification_status === "APPROVED").length,
    rework: complaints.filter((item) => item.verification_status === "REWORK_REQUIRED").length,
  };
  const departmentStatistics = Object.entries(
    complaints.reduce<Record<string, number>>((totals, complaint) => {
      totals[complaint.department] = (totals[complaint.department] ?? 0) + 1;
      return totals;
    }, {}),
  ).sort((left, right) => right[1] - left[1]);
  const selectedAssignmentComplaint = complaints.find(
    (item) => item.id === assignmentComplaintId,
  );

  return (
    <div className="app-shell">
      {mobileNav && <button className="mobile-backdrop" onClick={() => setMobileNav(false)} aria-label="Close menu" />}
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <a className="brand" href="#" onClick={(event) => event.preventDefault()}>
          <span className="brand-mark"><span /></span>
          <span className="brand-name">Nagarik<span>Setu</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {navItems.filter(({ name }) => name !== "Work tracking" || (user?.role !== "citizen" && user?.role !== "admin")).map(({ name, icon: Icon }) => (
            <button
              className={`nav-item ${page === name ? "nav-item-active" : ""}`}
              key={name}
              onClick={() => changePage(name)}
            >
              <Icon size={18} strokeWidth={1.8} />
              <span>{name}</span>
              {name === "Work tracking" && user?.role === "verifier" && counts.verification > 0 && (
                <span className="nav-count">{counts.verification}</span>
              )}

            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="help-card">
            <span className="help-icon"><Headphones size={17} /></span>
            <span className="help-copy"><strong>Need a hand?</strong><small>Visit our help center</small></span>
            <ArrowRight size={15} />
          </div>
          <button className="user-card" onClick={() => (token ? setProfileOpen(true) : setLoginOpen(true))}>
            <span className="avatar">{user ? user.name.slice(0, 1).toUpperCase() : "G"}</span>
            <span className="user-copy">
              <strong>{user?.name ?? "Guest workspace"}</strong>
              <small>{user ? roleLabels[user.role] : "Public workspace"}</small>
            </span>
            <ChevronDown size={16} />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open menu"><Menu size={20} /></button>
            <span className="breadcrumb-muted">City operations</span>
            <ChevronLeft className="breadcrumb-chevron" size={15} />
            <span className="breadcrumb-current">{page}</span>
          </div>
          <div className="topbar-actions">
            <div className="notification-wrap" ref={notificationsRef}>
              <button
                className="icon-button notification-button"
                aria-label={unreadNotifications.length > 0 ? `Notifications, ${unreadNotifications.length} unread updates` : "Notifications"}
                aria-expanded={notificationsOpen}
                aria-controls="notifications-panel"
                onClick={toggleNotifications}
              >
                <Bell size={18} />
                {unreadNotifications.length > 0 && (
                  <span className="notification-count">
                    {unreadNotifications.length > 9 ? "9+" : unreadNotifications.length}
                  </span>
                )}
              </button>
              {notificationsOpen && (
                <section className="notification-panel" id="notifications-panel" aria-label="Notifications">
                  <div className="notification-panel-heading">
                    <div><strong>Notifications</strong><small>Updates from your NagarikSetu workspace</small></div>
                    <button className="icon-button" onClick={() => setNotificationsOpen(false)} aria-label="Close notifications"><X size={16} /></button>
                  </div>
                  {!user ? (
                    <div className="notification-empty">
                      <Bell size={20} />
                      <p>Sign in to see updates for your reports and assigned work.</p>
                      <button className="button button-primary button-small" onClick={() => {setNotificationsOpen(false);setLoginOpen(true);}}>Sign in</button>
                    </div>
                  ) : notifications.length === 0 ? (
                    <div className="notification-empty"><CheckCircle2 size={20} /><p>You’re all caught up. There are no current updates.</p></div>
                  ) : (
                    <ul className="notification-list">
                      {notifications.map((notification) => (
                        <li key={notification.id}>
                          <button
                            className="notification-item"
                            onClick={() => changePage(notification.page)}
                          >
                            <span className="notification-item-icon"><Bell size={14} /></span>
                            <span><strong>{notification.title}</strong><small>{notification.detail}</small></span>
                            <ArrowRight size={14} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </div>
            {token ? (
              <button className="top-signin" onClick={signOut}>Sign out</button>
            ) : (
              <>
                <button className="top-signin" onClick={() => {setCitizenRegistrationOpen(true);setLoginOpen(false);}}><UserRoundPlus size={15} /> Sign up</button>
                <button className="top-signin" onClick={() => setLoginOpen(true)}><LogIn size={15} /> Sign in</button>
              </>
            )}
          </div>
        </header>

        <div className="page-content">
          {!apiOnline && !user && (
            <div className="demo-banner" role="status">
              <Sparkles size={14} />
              <span><strong>Live report data is unavailable.</strong> Check the service connection and retry.</span>
              <button onClick={() => void refreshPublicDashboard(new AbortController().signal)}>Retry connection <ArrowRight size={14} /></button>
            </div>
          )}

          {page === "Home" && user?.role === "engineer" && (
            <>
              <section className="welcome-row home-hero">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" /> FIELD OPERATIONS</div>
                  <h1>Engineer dashboard</h1>
                  <p className="page-subtitle">Your assignments, progress, and verification outcomes.</p>
                </div>
                <button className="button button-primary" onClick={() => changePage("Work tracking")}>Open assigned work <ArrowRight size={15} /></button>
              </section>
              <section className="metrics-grid" aria-label="Engineer work metrics">
                <MetricCard title="Assigned complaints" value={engineerDashboardMetrics.assigned} change="Visible to your account" icon={FileCheck2} tone="green" />
                <MetricCard title="New assignments" value={engineerDashboardMetrics.newAssignments} change="Ready to start" icon={Clock3} tone="blue" />
                <MetricCard title="In progress" value={engineerDashboardMetrics.inProgress} change="Active field work" icon={ArrowUpRight} tone="orange" />
                <MetricCard title="Awaiting review" value={engineerDashboardMetrics.awaitingReview} change="Submitted to verifier" icon={ShieldCheck} tone="red" />
              </section>
              <section className="content-grid">
                <div className="panel map-panel">
                  <div className="panel-heading"><div><h2>My work locations</h2><p>Only complaints assigned to you appear here.</p></div></div>
                  <ComplaintMap complaints={activeQueue} compact />
                </div>
                <div className="panel activity-panel">
                  <div className="panel-heading"><div><h2>Work needing action</h2><p>Continue or correct assigned work.</p></div></div>
                  <div className="attention-list">
                    {complaints.filter((item) => ["NOT_STARTED", "REWORK_IN_PROGRESS"].includes(item.engineer_work_status)).slice(0, 5).map((complaint) => <AttentionItem key={complaint.id} complaint={complaint} />)}
                    {engineerDashboardMetrics.rework > 0 && <p className="gps-review-warning">{engineerDashboardMetrics.rework} submission(s) need correction before resubmission.</p>}
                    {complaints.length === 0 && <p className="empty-state">No work is currently assigned to you.</p>}
                  </div>
                </div>
              </section>
              <section className="panel reports-panel">
                <div className="panel-heading reports-heading"><div><h2>Recent assignments</h2><p>Approved: {engineerDashboardMetrics.approved} · awaiting review: {engineerDashboardMetrics.awaitingReview}</p></div><button className="button button-light button-small" onClick={() => changePage("Work tracking")}>Manage work <ArrowRight size={14} /></button></div>
                <ComplaintTable complaints={complaints.slice(0, 5)} onSelect={(complaint) => void showWorkHistory(complaint)} />
              </section>
            </>
          )}

          {page === "Home" && user?.role === "officer" && (
            <>
              <section className="welcome-row home-hero">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" /> DEPARTMENT OPERATIONS</div>
                  <h1>Officer dashboard</h1>
                  <p className="page-subtitle">Triage reports, assign eligible engineers, and monitor verification outcomes.</p>
                </div>
                <button className="button button-primary" onClick={() => changePage("Work tracking")}>Manage assignments <ArrowRight size={15} /></button>
              </section>
              <section className="metrics-grid" aria-label="Department officer metrics">
                <MetricCard title="Active reports" value={counts.open} change="Across your departments" icon={FileCheck2} tone="green" />
                <MetricCard title="Pending assignment" value={officerDashboardMetrics.pendingAssignment} change="Needs an eligible engineer" icon={Clock3} tone="orange" />
                <MetricCard title="Awaiting verification" value={officerDashboardMetrics.awaitingReview} change="With assigned verifier" icon={ShieldCheck} tone="red" />
                <MetricCard title="Approved works" value={officerDashboardMetrics.approved} change="Verifier-approved" icon={CheckCircle2} tone="blue" />
              </section>
              <section className="content-grid">
                <div className="panel map-panel">
                  <div className="panel-heading"><div><h2>Department complaint map</h2><p>Exact locations are shown to authorized staff.</p></div><button className="button button-light button-small" onClick={() => changePage("Reports")}>View reports <ArrowRight size={14} /></button></div>
                  <ComplaintMap complaints={activeQueue} compact />
                </div>
                <div className="panel activity-panel">
                  <div className="panel-heading"><div><h2>Department breakdown</h2><p>Current complaint volume by department.</p></div></div>
                  <div className="attention-list">
                    {departmentStatistics.slice(0, 6).map(([department, total]) => <div className="department-stat-row" key={department}><span>{department}</span><strong>{total}</strong></div>)}
                    {departmentStatistics.length === 0 && <p className="empty-state">No complaints are currently available.</p>}
                  </div>
                  <div className="panel-bottom-note">{officerDashboardMetrics.rework} work submission(s) returned for correction.</div>
                </div>
              </section>
              <section className="panel reports-panel">
                <div className="panel-heading reports-heading"><div><h2>Recent department reports</h2><p>{officerDashboardMetrics.assigned} have an assigned engineer.</p></div><button className="button button-light button-small" onClick={() => changePage("Work tracking")}>Open work tracking <ArrowRight size={14} /></button></div>
                <ComplaintTable complaints={complaints.slice(0, 5)} onSelect={(complaint) => void showWorkHistory(complaint)} />
              </section>
            </>
          )}

          {page === "Home" && user?.role === "admin" && (
            <>
              <section className="welcome-row home-hero">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" /> SYSTEM ADMINISTRATION</div>
                  <h1>Administrator dashboard</h1>
                  <p className="page-subtitle">Invite official staff and manage account activation. Citizens register themselves; engineers require officer approval.</p>
                </div>
                <button className="button button-light" onClick={() => setProfileOpen(true)}>My profile</button>
              </section>
              <section className="metrics-grid" aria-label="Account metrics">
                <MetricCard title="Accounts" value={adminAccounts.length} change="Registered NagarikSetu users" icon={LayoutDashboard} tone="green" />
                <MetricCard title="Pending email verification" value={adminAccounts.filter((account) => !account.email_verified).length} change="New accounts awaiting confirmation" icon={Clock3} tone="orange" />
                <MetricCard title="Inactive accounts" value={adminAccounts.filter((account) => account.account_status === "INACTIVE").length} change="Access currently disabled" icon={ShieldCheck} tone="red" />
                <MetricCard title="Official roles" value={adminAccounts.filter((account) => ["officer", "verifier", "engineer"].includes(account.role)).length} change="Administrator-managed access" icon={CheckCircle2} tone="blue" />
              </section>
              <section className="content-grid">
                <div className="panel admin-invite-panel">
                  <div className="panel-heading"><div><h2>Invite a government official</h2><p>Only invited officer and verification-officer accounts can be activated.</p></div></div>
                  <form className="modal-form" onSubmit={(event) => void createOfficialInvitation(event)}>
                    <label>Full name<input name="name" required minLength={2} maxLength={120} /></label>
                    <label>Official email<input name="email" type="email" required minLength={6} maxLength={180} /></label>
                    <div className="form-two-col">
                      <label>Role<select name="role"><option value="officer">Government officer</option><option value="verifier">Verification officer</option></select></label>
                      <label>Employee ID<input name="employee_id" required minLength={2} maxLength={100} /></label>
                    </div>
                    <label>Designation<input name="designation" required minLength={2} maxLength={120} /></label>
                    <label>Department<input name="department" required minLength={2} maxLength={100} /></label>
                    <label>Jurisdiction<input name="jurisdiction" required minLength={2} maxLength={180} /></label>
                    {adminInvitationError && <p className="auth-error" role="alert">{adminInvitationError}</p>}
                    <button className="button button-primary"><Send size={15} /> Send invitation</button>
                  </form>
                </div>
                <div className="panel admin-accounts-panel">
                  <div className="panel-heading"><div><h2>Account access</h2><p>Deactivated accounts cannot sign in or use existing sessions.</p></div></div>
                  {adminAccountsError && <p className="auth-error" role="alert">{adminAccountsError}</p>}
                  <div className="admin-account-list">
                    {adminAccounts.map((account) => (
                      <div className="admin-account-row" key={account.id}>
                        <div>
                          <strong>{account.name}</strong>
                          <small>{account.email} · {roleLabels[account.role]}</small>
                          <small>{account.account_status} · {account.email_verified ? "Email verified" : "Email not verified"}</small>
                        </div>
                        <button
                          type="button"
                          className="button button-light button-small"
                          disabled={account.id === user.id && account.account_status === "ACTIVE"}
                          onClick={() => void changeAccountStatus(account)}
                        >
                          {account.account_status === "ACTIVE" ? "Deactivate" : "Activate"}
                        </button>
                      </div>
                    ))}
                    {adminAccounts.length === 0 && !adminAccountsError && <p className="empty-state">No accounts are available yet.</p>}
                  </div>
                </div>
              </section>
            </>
          )}

          {page === "Home" && user?.role === "verifier" && (
            <>
              <section className="welcome-row home-hero">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" /> INDEPENDENT WORK VERIFICATION</div>
                  <h1>Verification dashboard</h1>
                  <p className="page-subtitle">Review evidence only for complaints assigned to your verifier account.</p>
                </div>
                <button className="button button-primary" onClick={() => changePage("Work tracking")}>Open review queue <ArrowRight size={15} /></button>
              </section>
              <section className="metrics-grid" aria-label="Verification metrics">
                <MetricCard title="Awaiting review" value={verificationQueue.length} change="Assigned to you" icon={Clock3} tone="orange" />
                <MetricCard title="Approved works" value={complaints.filter((item) => item.verification_status === "APPROVED").length} change="Your review history" icon={CheckCircle2} tone="green" />
                <MetricCard title="Rework requested" value={complaints.filter((item) => item.verification_status === "REWORK_REQUIRED").length} change="Returned for correction" icon={ArrowUpRight} tone="red" />
                <MetricCard title="Assigned reports" value={complaints.length} change="Scoped to your account" icon={FileCheck2} tone="blue" />
              </section>
              <section className="workflow-list">
                <div className="panel-heading"><div><h2>Submissions to review</h2><p>Compare the submitted evidence and GPS details before deciding.</p></div><span className="review-count"><ShieldCheck size={15} /> {verificationQueue.length} awaiting review</span></div>
                {verificationQueueError && <p className="auth-error" role="alert">{verificationQueueError}</p>}
                {verificationQueueLoading && verificationQueue.length === 0 && <p className="empty-state">Loading your assigned submissions…</p>}
                {!verificationQueueLoading && !verificationQueueError && verificationQueue.length === 0 && <div className="panel empty-review"><CheckCircle2 size={26} /><h2>You’re all caught up</h2><p>No work submissions are awaiting your review.</p></div>}
                {verificationQueue.length > 0 && <div className="review-grid">{verificationQueue.slice(0, 4).map((item) => (
                  <article className="panel review-card" key={item.submission.id}>
                    <div className="review-card-top"><span className="severity severity-high">Awaiting review</span><span>{item.complaint.reference}</span></div>
                    <h2>{item.complaint.title}</h2>
                    <p><MapPin size={13} /> {Math.round(item.submission.distance_from_complaint_meters)} m from complaint location</p>
                    <button className="button button-primary review-button" onClick={() => setSelectedReview(item)}>Review evidence <ArrowRight size={14} /></button>
                  </article>
                ))}</div>}
              </section>
            </>
          )}

          {page === "Home" && (!user || user.role === "citizen") && (
            <>
              <section className="welcome-row home-hero">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" /> {now.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })} · {now.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</div>
                  <h1>{now.getHours() < 12 ? "Good morning" : now.getHours() < 17 ? "Good afternoon" : "Good evening"}{user ? `, ${user.name.split(" ")[0]}` : ""} <span className="wave">✳</span></h1>
                  <p className="page-subtitle">Here’s what’s happening across your city today.</p>
                </div>
                <button className="button button-primary" onClick={() => {setReportCoordinates({ latitude: "", longitude: "" });setReportLocationEvidence(null);setReportOpen(true);}}><Plus size={17} /> New report</button>
              </section>
              <section className="metrics-grid" aria-label="City overview metrics">
                <MetricCard title="Active reports" value={counts.open} change={user ? "Current complaint queue" : "Public dashboard"} icon={FileCheck2} tone="green" />
                <MetricCard title="Awaiting review" value={counts.verification} change="Needs officer review" icon={Clock3} tone="orange" />
                <MetricCard title="High priority" value={counts.urgent} change="Critical & high severity" icon={ArrowUpRight} tone="red" />
                <MetricCard title="Officially resolved" value={counts.resolved} change="Officer-approved closures" icon={CheckCircle2} tone="blue" />
              </section>

              <section className="content-grid">
                <div className="panel map-panel">
                  <div className="panel-heading">
                    <div><h2>Community reports</h2><p>{!user ? "Public reports · locations are generalized" : user.role === "citizen" ? "Your submitted reports" : user.role === "engineer" ? "Your assigned reports" : "Reports across the service area"}</p></div>
                    <button className="button button-light button-small" onClick={() => changePage("Reports")}>View reports <ArrowRight size={14} /></button>
                  </div>
                  <ComplaintMap complaints={activeQueue} compact />
                  <div className="map-footer">
                    <span><i className="legend-dot legend-critical" /> Critical <b>{activeQueue.filter((item) => item.severity === "Critical").length}</b></span>
                    <span><i className="legend-dot legend-high" /> High <b>{activeQueue.filter((item) => item.severity === "High").length}</b></span>
                    <span><i className="legend-dot legend-medium" /> Medium <b>{activeQueue.filter((item) => item.severity === "Medium").length}</b></span>
                  </div>
                </div>

                <div className="panel activity-panel">
                  <div className="panel-heading">
                    <div><h2>Needs attention</h2><p>Priority items to look at</p></div>
                    <button className="text-button" onClick={() => changePage("Reports")}>View all</button>
                  </div>
                  <div className="attention-list">
                    {activeQueue.slice(0, 4).map((complaint) => (
                      <AttentionItem key={complaint.id} complaint={complaint} />
                    ))}
                    {activeQueue.length === 0 && <p className="empty-state">No open reports need attention.</p>}
                  </div>
                  <div className="panel-bottom-note"><span className="pulse-dot" /> Data refreshed {dashboardUpdatedAt?.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) ?? "pending"} <span className="note-divider">·</span> {counts.open} open reports</div>
                </div>
              </section>

              <section className="panel reports-panel">
                <div className="panel-heading reports-heading">
                  <div><h2>Recent reports</h2><p>{user ? "Keep track of what’s moving" : "Public complaint and resolution status"}</p></div>
                  <button className="button button-light button-small" onClick={() => changePage("Reports")}>All reports <ArrowRight size={14} /></button>
                </div>
                <ComplaintTable complaints={complaints.slice(0, 5)} onSelect={user ? (complaint) => void showWorkHistory(complaint) : undefined} />
              </section>
            </>
          )}

          {page === "Reports" && (
            <>
              <section className="welcome-row">
                <div><div className="eyebrow"><span className="eyebrow-dot" /> CASE MANAGEMENT</div><h1>Reports & requests</h1><p className="page-subtitle">A clear view of every civic issue raised in your area.</p></div>
                <button className="button button-primary" onClick={() => {setReportCoordinates({ latitude: "", longitude: "" });setReportLocationEvidence(null);setReportOpen(true);}}><Plus size={17} /> New report</button>
              </section>
              <section className="panel reports-panel">
                <div className="report-toolbar">
                  <label className="search-field"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search reports, locations..." /></label>
                  <label className="filter-field"><Filter size={15} /><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option>All categories</option>{Array.from(new Set(complaints.map((item) => item.category))).map((category) => <option key={category}>{category}</option>)}</select></label>
                </div>
                <ComplaintTable complaints={filteredComplaints} onSelect={user ? (complaint) => void showWorkHistory(complaint) : undefined} />
                {filteredComplaints.length === 0 && <div className="empty-state table-empty">No reports match your search.</div>}
              </section>
            </>
          )}

          {page === "Government schemes" && (
            <>
              <section className="welcome-row">
                <div><div className="eyebrow"><span className="eyebrow-dot" /> DOCUMENT-GROUNDED GUIDANCE</div><h1>Government schemes</h1><p className="page-subtitle">Understand schemes and public services with cited, plain-language answers.</p></div>
              </section>
              <section className="panel scheme-catalog">
                <div className="panel-heading">
                  <div><h2>Featured government schemes</h2><p>Public information and official portals, available without signing in.</p></div>
                </div>
                <div className="scheme-card-grid">
                  {featuredSchemes.map((scheme) => (
                    <article className="scheme-card" key={scheme.title}>
                      <span className="scheme-category">{scheme.category}</span>
                      <h3>{scheme.title}</h3>
                      <p>{scheme.description}</p>
                      <a href={scheme.source_url} target="_blank" rel="noreferrer">Official portal <ArrowUpRight size={14} /></a>
                      {schemeTasks.filter((task) => task.scheme_title === scheme.title).length > 0 && (
                        <div className="scheme-linked-tasks">
                          <strong>Linked work</strong>
                          {schemeTasks
                            .filter((task) => task.scheme_title === scheme.title)
                            .map((task) => (
                              <div className="scheme-linked-task" key={task.id}>
                                <b>{task.title}</b>
                                <small>{statusLabel(task.status)} · {task.department}</small>
                                <small>
                                  Assigned to {task.assigned_engineer?.name ?? "Engineer"}
                                  {task.assigned_engineer?.registration_number
                                    ? ` · Registration ${task.assigned_engineer.registration_number}`
                                    : ""}
                                </small>
                                {task.assigned_engineer?.skills.length ? (
                                  <small>Skills: {task.assigned_engineer.skills.join(", ")}</small>
                                ) : null}
                              </div>
                            ))}
                        </div>
                      )}
                    </article>
                  ))}
                </div>
                {schemeTasksError && <p className="scheme-error" role="status">{schemeTasksError}</p>}
              </section>
              <section className="panel scheme-catalog approved-scheme-documents">
                <div className="panel-heading">
                  <div><h2>Approved scheme documents</h2><p>Documents published by a department officer.</p></div>
                </div>
                {schemeDocumentsLoading && <p className="empty-state scheme-message">Loading approved documents…</p>}
                {schemeDocumentsError && <p className="scheme-error" role="status">{schemeDocumentsError}</p>}
                {!schemeDocumentsLoading && !schemeDocumentsError && schemeDocuments.length === 0 && (
                  <p className="empty-state scheme-message">No officer-approved documents have been added yet. The official scheme portals above are available in the meantime.</p>
                )}
                {schemeDocuments.length > 0 && (
                  <div className="scheme-document-list">
                    {schemeDocuments.map((document) => (
                      <article className="scheme-document" key={`${document.title}-${document.version}`}>
                        <BookOpen size={17} />
                        <span><strong>{document.title}</strong><small>Version {document.version} · Approved source</small></span>
                        {document.source_url && <a href={document.source_url} target="_blank" rel="noreferrer">Open source <ArrowUpRight size={13} /></a>}
                      </article>
                    ))}
                  </div>
                )}
              </section>
              <section className="assistant-layout">
                <div className="panel assistant-panel">
                  <div className="assistant-top"><span className="assistant-avatar"><Sparkles size={17} /></span><span><strong>NagarikSetu Guide</strong><small>Scheme information and engineer work help</small></span><span className="grounded-badge"><ShieldCheck size={13} /> Grounded answers</span></div>
                  <div className="chat-body">
                    {chatMessages.length === 0 && <div className="assistant-intro"><span className="assistant-spark"><Sparkles size={22} /></span><h2>A little clarity goes a long way.</h2><p>Ask about government schemes or how engineers track and submit assigned work. Scheme answers cite approved documents; workflow answers use the NagarikSetu engineer guide.</p><div className="suggested-questions"><button onClick={() => setChatQuestion("What should I check before applying for a government scheme?")}>What should I check before applying? <ArrowRight size={14} /></button><button onClick={() => setChatQuestion("How do I track and submit my assigned work as an engineer?")}>How do I track assigned work? <ArrowRight size={14} /></button></div></div>}
                    {chatMessages.map((message, index) => <div className={`chat-message chat-${message.role}`} key={`${message.role}-${index}`}><div className="chat-bubble">{message.content}{message.sources?.map((source) => <div className="citation-card" key={`${source.title}-${source.version}`}><BookOpen size={14} /><span><strong>{source.title}</strong><small>Version {source.version} · Approved source</small><small>{source.excerpt}</small></span>{source.source_url && <a href={source.source_url} target="_blank" rel="noreferrer">Source</a>}</div>)}</div></div>)}
                    {chatLoading && <div className="typing-indicator"><i /><i /><i /> Searching approved documents…</div>}
                  </div>
                  <form className="chat-form" onSubmit={(event) => void sendQuestion(event)}><input value={chatQuestion} onChange={(event) => setChatQuestion(event.target.value)} placeholder="Ask about a scheme or civic service..." aria-label="Your question" /><button className="send-button" disabled={chatLoading || !chatQuestion.trim()} aria-label="Send question"><Send size={17} /></button></form>
                  {!user && <p className="assistant-footnote">Sign in to ask the document-grounded assistant. The scheme directory above is public.</p>}
                  <p className="assistant-footnote"><ShieldCheck size={13} /> Guidance only, not an official eligibility decision.</p>
                </div>
                <aside className="panel assistant-info"><span className="info-icon"><BookOpen size={18} /></span><h3>Built on trusted sources</h3><p>Scheme answers use officer-approved documents. Engineer answers explain the app workflow and never make official decisions.</p><div className="info-separator" /><div className="info-fact"><span className="fact-check"><Check size={13} /></span><span><strong>Source citations</strong><small>Review the document behind an answer.</small></span></div><div className="info-fact"><span className="fact-check"><Check size={13} /></span><span><strong>English & Kannada</strong><small>Ask in the language that works for you.</small></span></div><div className="guidance-callout"><ShieldCheck size={15} /><span>Scheme information is general guidance, not an official approval.</span></div></aside>
              </section>
            </>
          )}

          {page === "Work tracking" && (
            <>
              <section className="welcome-row">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" /> ASSIGNMENT & FIELD OPERATIONS</div>
                  <h1>Work tracking</h1>
                  <p className="page-subtitle">Follow assigned work, progress updates, photos, and independent reviews.</p>
                </div>
              </section>
              {!user && <div className="panel empty-review"><ShieldCheck size={24} /><h2>Sign in to access work management</h2><p>Engineers see their assignments; department officers review registrations and assign crews.</p><button className="button button-primary" onClick={() => setLoginOpen(true)}>Sign in</button></div>}
              {user?.role === "engineer_pending" && <div className="panel registration-status-panel"><span className="review-count"><Clock3 size={15} /> {registrationStatus || "PENDING"}</span><h2>{registrationStatus === "REJECTED" ? "Registration needs changes" : "Engineer account awaiting approval"}</h2><p>{registrationStatus === "REJECTED" ? "An officer rejected this application. Review the reason, update your details, and resubmit for another review." : "Your registration details have been submitted. An officer must approve them before complaint access or assignment is enabled."}</p>{registrationReviewReason && <div className="registration-reason"><b>Officer review reason</b><p>{registrationReviewReason}</p></div>}{registrationStatus === "REJECTED" && registrationProfile && <form className="modal-form resubmit-form" onSubmit={(event) => void resubmitEngineerRegistration(event)}><label>Department<input name="department" required minLength={2} maxLength={100} defaultValue={registrationProfile.department} /></label><label>Professional registration number<input name="registration_number" required minLength={2} maxLength={100} defaultValue={registrationProfile.registration_number} /></label><label>Skills, separated by commas<input name="skills" required defaultValue={registrationProfile.skills.join(", ")} /></label><label>Application note<textarea name="application_note" required minLength={10} maxLength={2000} rows={3} defaultValue={registrationProfile.application_note} /></label><button className="button button-primary">Resubmit application</button></form>}</div>}
              {user?.role === "engineer" && (
                <>
                  <div className="workflow-status"><ShieldCheck size={16} /><span>Registration approved</span><strong>{registrationStatus || "APPROVED"}</strong></div>
                  <section className="workflow-list">
                    <div className="panel-heading"><div><h2>My assigned work</h2><p>Your approved engineer account uses this same NagarikSetu sign-in. Start, update, and submit your assigned work here.</p></div></div>
                    {complaints.length === 0 && <div className="empty-review"><h2>No assignments yet</h2><p>Your assigned civic work will appear here after an officer assigns it.</p></div>}
                    {complaints.map((complaint) => (
                      <article className="panel work-card" key={complaint.id}>
                        <div className="work-card-heading"><div><span className="eyebrow">{complaint.reference} · {complaint.department}</span><h2>{complaint.title}</h2><p><MapPin size={14} /> {complaint.address}</p></div><StatusBadge status={complaint.official_status} /></div>
                        {complaint.assigned_engineer && (
                          <div className="assigned-engineer-info">
                            <strong>Assigned engineer</strong>
                            <span>{complaint.assigned_engineer.name}</span>
                            <small>{complaint.assigned_engineer.department} · Registration {complaint.assigned_engineer.registration_number}</small>
                            <small>Skills: {complaint.assigned_engineer.skills.join(", ")}</small>
                          </div>
                        )}
                        <div className="work-card-actions">
                          {["NOT_STARTED", "REWORK_IN_PROGRESS"].includes(complaint.engineer_work_status) && <button className="button button-primary" onClick={() => void startWork(complaint)}><CheckCircle2 size={15} /> {complaint.engineer_work_status === "REWORK_IN_PROGRESS" ? "Resume rework" : "Start work"}</button>}
                          {complaint.engineer_work_status === "IN_PROGRESS" && <><form className="progress-form" onSubmit={(event) => void updateWorkProgress(event, complaint)}><label>Progress update<input name="note" required minLength={5} maxLength={2000} placeholder="Describe the work completed so far" /></label><button className="button button-light">Save update</button></form><button className="button button-primary" onClick={() => openWorkSubmission(complaint)}>Submit completion</button></>}
                          {complaint.engineer_work_status === "SUBMITTED_FOR_VERIFICATION" && <span className="workflow-status"><Clock3 size={15} /> Awaiting independent verification</span>}
                        </div>
                        {complaint.engineer_work_status === "IN_PROGRESS" && (
                          <div className="location-sharing-control">
                            <span><MapPin size={14} /> Live location is visible to government officers only.</span>
                            {locationSharing.has(`complaint:${complaint.id}`)
                              ? <button className="button button-light" onClick={() => stopLiveLocationTracking(`complaint:${complaint.id}`)}>Stop sharing</button>
                              : <button className="button button-light" onClick={() => startLiveLocationTracking(`complaint:${complaint.id}`, `/api/complaints/${complaint.id}/work/location`)}>Share live location</button>}
                          </div>
                        )}
                        <button className="text-button work-history-link" onClick={() => void showWorkHistory(complaint)}>View work history <ArrowRight size={14} /></button>
                      </article>
                    ))}
                  </section>
                  <section className="workflow-list scheme-task-list">
                    <div className="panel-heading"><div><h2>Scheme-linked work</h2><p>Tasks assigned to your approved engineer account by a department officer.</p></div></div>
                    {schemeTasks.length === 0 && <div className="panel empty-review"><h2>No scheme work assigned</h2><p>Officer-assigned scheme tasks will appear here with the related scheme and engineer details.</p></div>}
                    {schemeTasks.map((task) => (
                      <article className="panel scheme-task-card" key={task.id}>
                        <div className="work-card-heading"><div><span className="eyebrow">{task.scheme_title} · {task.department}</span><h2>{task.title}</h2><p>{task.description}</p></div><StatusBadge status={task.status} /></div>
                        {task.assigned_engineer && (
                          <div className="assigned-engineer-info">
                            <strong>Assigned engineer</strong>
                            <span>{task.assigned_engineer.name}</span>
                            <small>{task.assigned_engineer.department} · Registration {task.assigned_engineer.registration_number}</small>
                            <small>Skills: {task.assigned_engineer.skills.join(", ")}</small>
                          </div>
                        )}
                        {task.progress_note && <p className="scheme-task-progress"><b>Latest progress:</b> {task.progress_note}</p>}
                        {task.updates && task.updates.length > 0 && (
                          <ol className="scheme-task-updates">
                            {task.updates.slice(-3).map((update) => (
                              <li key={`${update.created_at}-${update.event_type}`}>
                                <strong>{statusLabel(update.event_type)}</strong>
                                <span>{update.note}</span>
                                <small>{update.actor} · {new Date(update.created_at).toLocaleString()}</small>
                              </li>
                            ))}
                          </ol>
                        )}
                        <div className="work-card-actions">
                          {task.status === "ASSIGNED" && <button className="button button-primary" onClick={() => void updateSchemeTask(task, "start")}><CheckCircle2 size={15} /> Start scheme work</button>}
                          {task.status === "IN_PROGRESS" && (
                            <>
                              <form className="progress-form" onSubmit={(event) => {
                                event.preventDefault();
                                const formElement = event.currentTarget;
                                const form = new FormData(formElement);
                                void updateSchemeTask(task, "progress", { note: String(form.get("note") ?? "") }).then((saved) => {
                                  if (saved) formElement.reset();
                                });
                              }}>
                                <label>Progress update<input name="note" required minLength={5} maxLength={2000} placeholder="Describe the work completed so far" /></label>
                                <button className="button button-light">Save update</button>
                              </form>
                              <form className="scheme-task-complete-form" onSubmit={(event) => {
                                event.preventDefault();
                                const formElement = event.currentTarget;
                                const form = new FormData(formElement);
                                void updateSchemeTask(task, "complete", { note: String(form.get("note") ?? "") }).then((saved) => {
                                  if (saved) formElement.reset();
                                });
                              }}>
                                <label>Completion note<input name="note" required minLength={10} maxLength={2000} placeholder="Summarize the completed scheme work" /></label>
                                <button className="button button-primary"><CheckCircle2 size={15} /> Mark complete</button>
                              </form>
                            </>
                          )}
                        </div>
                        {task.status === "IN_PROGRESS" && (
                          <div className="location-sharing-control">
                            <span><MapPin size={14} /> Live location is visible to government officers only.</span>
                            {locationSharing.has(`scheme:${task.id}`)
                              ? <button className="button button-light" onClick={() => stopLiveLocationTracking(`scheme:${task.id}`)}>Stop sharing</button>
                              : <button className="button button-light" onClick={() => startLiveLocationTracking(`scheme:${task.id}`, `/api/scheme-tasks/${task.id}/location`)}>Share live location</button>}
                          </div>
                        )}
                      </article>
                    ))}
                  </section>
                </>
              )}
              {user?.role === "officer" && (
                <>
                  <div className="workflow-columns">
                    <section className="panel workflow-panel">
                    <div className="panel-heading"><div><h2>Engineer registrations</h2><p>Review credentials before granting complaint access.</p></div><span className="review-count">{engineerApplications.length} pending</span></div>
                    {engineerApplications.length === 0 && <p className="empty-state workflow-empty">No engineer applications await review.</p>}
                    {engineerApplications.map((application) => (
                      <article className="application-card" key={application.user_id}>
                        <span className="eyebrow">{application.registration_number} · {application.department}</span>
                        <h3>{application.name}</h3><p>{application.email}</p>
                        <p><b>Skills</b> · {application.skills.join(", ")}</p>
                        <p>{application.application_note}</p>
                        <label className="application-reason">Review reason<textarea value={applicationReasons[application.user_id] ?? ""} onChange={(event) => setApplicationReasons((current) => ({ ...current, [application.user_id]: event.target.value }))} minLength={8} maxLength={2000} rows={2} placeholder="Record the basis for your decision" /></label>
                        <div className="application-actions"><button className="button button-primary" onClick={() => void reviewEngineerApplication(application, "APPROVED")}>Approve registration</button><button className="button button-light" onClick={() => void reviewEngineerApplication(application, "REJECTED")}>Reject</button></div>
                      </article>
                    ))}
                    </section>
                    <section className="panel workflow-panel">
                    <div className="panel-heading"><div><h2>Assign civic work</h2><p>Engineers must be approved and match the report’s department and skill requirements.</p></div></div>
                    {selectedAssignmentComplaint?.assessment && !selectedAssignmentComplaint.engineer_id && (
                      <form className="modal-form triage-review-form" onSubmit={(event) => void reviewTriage(event)}>
                        <div className="modal-note"><ShieldCheck size={15} /> Preliminary keyword recommendation only. Review and confirm or change it before assignment.</div>
                        <label>Officer-confirmed category<select name="category" defaultValue={selectedAssignmentComplaint.assessment.suggested_category}><option>Roads & pavements</option><option>Water & drainage</option><option>Street lighting</option><option>Waste management</option><option>Pollution & environment</option></select></label>
                        <label>Officer-confirmed priority<select name="severity" defaultValue={selectedAssignmentComplaint.assessment.suggested_severity}><option>Critical</option><option>High</option><option>Medium</option><option>Low</option></select></label>
                        <label>Review reason<textarea name="reason" required minLength={8} maxLength={2000} rows={2} placeholder="Record why you confirmed or changed this suggestion..." /></label>
                        <button className="button button-light"><ShieldCheck size={15} /> Save triage review</button>
                      </form>
                    )}
                    {!complaints.some((item) => !["CLOSED", "OFFICIALLY_COMPLETED"].includes(item.official_status) && item.verification_status !== "PENDING_REVIEW") ? (
                      <p className="empty-state workflow-empty">There are no reports ready for assignment.</p>
                    ) : verificationOfficers.length === 0 ? (
                      <p className="empty-state workflow-empty">A verification officer is required before work can be assigned.</p>
                    ) : (
                      <form className="modal-form assignment-form" onSubmit={(event) => void assignWork(event)}>
                        <label>Complaint<select name="complaint_id" required value={assignmentComplaintId} onChange={(event) => setAssignmentComplaintId(event.target.value)}>{complaints.filter((item) => !["CLOSED", "OFFICIALLY_COMPLETED"].includes(item.official_status) && item.verification_status !== "PENDING_REVIEW").map((item) => <option value={item.id} key={item.id}>{item.reference} · {item.title} · {item.department}</option>)}</select></label>
                        <label>Eligible registered engineer<select required value={assignmentEngineerId} onChange={(event) => setAssignmentEngineerId(event.target.value)} disabled={assignmentEligibilityLoading || eligibleEngineers.length === 0}>
                          {eligibleEngineers.length === 0 ? <option value="">{assignmentEligibilityLoading ? "Checking approved engineers…" : "No approved engineer matches this department and report category"}</option> : eligibleEngineers.map((engineer) => <option value={engineer.id} key={engineer.id}>{engineer.name} · {engineer.department} · {engineer.skills.join(", ")}</option>)}
                        </select></label>
                        <label>Independent verification officer<select required value={assignmentVerifierId} onChange={(event) => setAssignmentVerifierId(event.target.value)}>{verificationOfficers.map((officer) => <option value={officer.id} key={officer.id}>{officer.name}</option>)}</select></label>
                        <button className="button button-primary" disabled={assignmentEligibilityLoading || !assignmentEngineerId || !assignmentVerifierId}><CheckCircle2 size={15} /> Assign work</button>
                      </form>
                    )}
                    </section>
                  </div>
                  <div className="workflow-columns scheme-operations">
                    <section className="panel workflow-panel">
                      <div className="panel-heading"><div><h2>Create scheme-linked work</h2><p>Assign a task to an approved engineer whose department and registered skills match.</p></div></div>
                      <form className="modal-form scheme-task-form" onSubmit={(event) => void createSchemeTask(event)}>
                        <label>Government scheme<select name="scheme_title" required defaultValue=""><option value="" disabled>Select a scheme</option>{featuredSchemes.map((scheme) => <option value={scheme.title} key={scheme.title}>{scheme.title}</option>)}</select></label>
                        <label>Work title<input name="title" required minLength={5} maxLength={180} placeholder="Describe the field task" /></label>
                        <label>Task details<textarea name="description" required minLength={10} maxLength={2000} rows={3} placeholder="Explain the work to complete under this scheme" /></label>
                        <label>Department<select value={schemeTaskDepartment} onChange={(event) => setSchemeTaskDepartment(event.target.value)}><option>Public Works</option><option>Water Supply</option><option>Electrical</option><option>Solid Waste</option><option>Environment</option></select></label>
                        <label>Required engineer skills<input name="required_skills" required value={schemeTaskSkills} onChange={(event) => setSchemeTaskSkills(event.target.value)} placeholder="Comma-separated, e.g. road repair" /></label>
                        <label>Eligible engineer<select required value={schemeTaskEngineerId} onChange={(event) => setSchemeTaskEngineerId(event.target.value)} disabled={schemeTaskEligibilityLoading || schemeEligibleEngineers.length === 0}>
                          {schemeEligibleEngineers.length === 0
                            ? <option value="">{schemeTaskEligibilityLoading ? "Checking eligibility…" : "No approved engineer matches these requirements"}</option>
                            : schemeEligibleEngineers.map((engineer) => <option value={engineer.id} key={engineer.id}>{engineer.name} · {engineer.department} · {engineer.registration_number}</option>)}
                        </select></label>
                        <button className="button button-primary" disabled={schemeTaskEligibilityLoading || !schemeTaskEngineerId}><CheckCircle2 size={15} /> Assign scheme work</button>
                      </form>
                      <div className="scheme-admin-task-list">
                        <h3>Scheme work assignments</h3>
                        {schemeTasks.length === 0 && <p className="empty-state">No scheme tasks have been assigned.</p>}
                        {schemeTasks.map((task) => (
                          <article className="scheme-admin-task" key={task.id}>
                            <span className="eyebrow">{task.scheme_title} · {statusLabel(task.status)}</span>
                            <strong>{task.title}</strong>
                            <small>{task.department} · {task.required_skills.join(", ")}</small>
                            <small>Assigned engineer: {task.assigned_engineer?.name ?? "Unavailable"} · Registration {task.assigned_engineer?.registration_number ?? "—"}</small>
                            {task.progress_note && <small>Latest progress: {task.progress_note}</small>}
                          </article>
                        ))}
                      </div>
                    </section>
                    <section className="panel workflow-panel">
                      <div className="panel-heading"><div><h2>Live engineer locations</h2><p>Officers only · Refreshes every 15 seconds. Only the latest shared coordinate is retained.</p></div><span className="review-count"><MapPin size={14} /> {liveLocations.length} sharing</span></div>
                      {liveLocationError && <p className="scheme-error" role="status">{liveLocationError}</p>}
                      {liveLocations.length === 0 && !liveLocationError && <p className="empty-state workflow-empty">No active engineer is currently sharing live location. Engineers must start assigned work and opt in.</p>}
                      {liveLocations.length > 0 && (
                        <div className="live-location-map">
                          <MapContainer center={[liveLocations[0].latitude, liveLocations[0].longitude]} zoom={12} scrollWheelZoom={false}>
                            <TileLayer attribution='Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community' url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" />
                            {liveLocations.map((location) => (
                              <CircleMarker key={`${location.work_type}-${location.work_id}`} center={[location.latitude, location.longitude]} radius={8} pathOptions={{ color: "#fff", weight: 2, fillColor: "#4b9b68", fillOpacity: 0.95 }}>
                                <Popup><strong>{location.assigned_engineer.name}</strong><br />{location.title}<br />{location.reference ?? location.scheme_title}</Popup>
                              </CircleMarker>
                            ))}
                          </MapContainer>
                        </div>
                      )}
                      <div className="live-location-list">
                        {liveLocations.map((location) => (
                          <article className="live-location-card" key={`${location.work_type}-${location.work_id}`}>
                            <span className="eyebrow">{location.reference ?? location.scheme_title} · {location.work_type === "scheme" ? "Scheme work" : "Complaint work"}</span>
                            <strong>{location.title}</strong>
                            <span>{location.assigned_engineer.name} · {location.assigned_engineer.department}</span>
                            <small>Registration {location.assigned_engineer.registration_number} · Skills: {location.assigned_engineer.skills.join(", ")}</small>
                            <small>Coordinates {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}</small>
                            <small>Last received {new Date(location.updated_at).toLocaleString()}</small>
                          </article>
                        ))}
                      </div>
                    </section>
                  </div>
                </>
              )}
              {user?.role === "verifier" && (
                <section className="workflow-list">
                  <div className="panel-heading"><div><h2>Submissions to review</h2><p>Review submitted photos and record your decision.</p></div><span className="review-count"><ShieldCheck size={15} /> {verificationQueue.length} awaiting review</span></div>
                  {verificationQueueError && <p className="auth-error" role="alert">{verificationQueueError}</p>}
                  {verificationQueueLoading && verificationQueue.length === 0 && <p className="empty-state">Loading your assigned submissions…</p>}
                  {!verificationQueueLoading && !verificationQueueError && verificationQueue.length === 0 && <div className="panel empty-review"><CheckCircle2 size={26} /><h2>You’re all caught up</h2><p>No work submissions are awaiting your review.</p></div>}
                  {verificationQueue.length > 0 && <div className="review-grid">{verificationQueue.map((item) => (
                    <div className="panel review-card" key={item.submission.id}>
                      <div className="review-card-top"><span className="severity severity-high">Awaiting review</span><span>Attempt {item.submission.attempt_number}</span></div>
                      <h2>{item.complaint.title}</h2>
                      <p><MapPin size={14} /> {item.complaint.address}</p>
                      <div className="review-evidence">
                        <span><FileCheck2 size={16} /><b>Before</b><small>{item.submission.before_evidence.startsWith("data:image/") ? "Engineer photo" : item.submission.before_evidence}</small></span>
                        <ArrowRight size={15} />
                        <span><CheckCircle2 size={16} /><b>After</b><small>{item.submission.after_evidence.startsWith("data:image/") ? "Engineer photo" : item.submission.after_evidence}</small></span>
                      </div>
                      <div className="evidence-images">
                        <EvidencePhoto label="Before" evidence={item.submission.before_evidence} />
                        <EvidencePhoto label="After" evidence={item.submission.after_evidence} />
                      </div>
                      <div className="review-notes"><b>Work details</b><p>{item.submission.work_details}</p><small>{item.submission.completion_notes}</small></div>
                      <button className="button button-primary review-button" onClick={() => setSelectedReview(item)}>Review evidence <ArrowRight size={15} /></button>
                    </div>
                  ))}</div>}
                </section>
              )}
            </>
          )}

          {page === "Engineer registration" && (
            <>
              <section className="welcome-row">
                <div><div className="eyebrow"><span className="eyebrow-dot" /> ENGINEER ACCESS</div><h1>Engineer registration</h1><p className="page-subtitle">Apply for access to assigned civic work. All applications are reviewed by a department officer.</p></div>
              </section>
              {user?.role === "engineer" || user?.role === "engineer_pending" ? (
                <section className="panel registration-status-panel">
                  <span className="review-count"><ShieldCheck size={15} /> {user.role === "engineer" ? "APPROVED" : registrationStatus || "PENDING"}</span>
                  <h2>{user.role === "engineer" ? "Your registration is approved" : registrationStatus === "REJECTED" ? "Your registration needs changes" : registrationStatus === "PENDING" ? "Your application is being reviewed" : "Your application is on file"}</h2>
                  <p>Go to Work tracking to view your status, resubmit if needed, and check assigned work.</p>
                  <button className="button button-primary" onClick={() => changePage("Work tracking")}>Open work tracking <ArrowRight size={15} /></button>
                </section>
              ) : (
                <section className="panel empty-review">
                  <UserRoundPlus size={25} />
                  <h2>Apply to work as a field engineer</h2>
                  <p>Submit your professional details for department officer review. Approved engineers can receive and track assigned reports.</p>
                  <button className="button button-primary" onClick={() => setEngineerRegistrationOpen(true)}>Start registration <ArrowRight size={15} /></button>
                </section>
              )}
            </>
          )}
          <footer className="page-footer"><span>© 2026 NagarikSetu <i>·</i> Transparent service, together.</span><span><span className="footer-status" /> Systems operational <i>·</i> Privacy-first civic tech</span></footer>
        </div>
      </main>

      {assistantOpen && (
        <section className="assistant-widget-panel" role="dialog" aria-label="NagarikSetu Guide">
          <div className="assistant-top assistant-widget-header">
            <span className="assistant-avatar"><Sparkles size={17} /></span>
            <span><strong>NagarikSetu Guide</strong><small>Schemes and engineer work help</small></span>
            <button className="assistant-widget-close" onClick={() => setAssistantOpen(false)} aria-label="Close NagarikSetu Guide"><X size={17} /></button>
          </div>
          <div className="chat-body assistant-widget-body" aria-live="polite">
            {chatMessages.length === 0 && (
              <div className="assistant-intro">
                <span className="assistant-spark"><Sparkles size={22} /></span>
                <h2>How can I help?</h2>
                <p>I can explain scheme guidance from approved documents and walk engineers through assigned work, progress updates, photos, and verification.</p>
                <div className="suggested-questions">
                  <button type="button" onClick={() => setChatQuestion("Explain the available government scheme information and official sources.")}>Explain government schemes <ArrowRight size={14} /></button>
                  <button type="button" onClick={() => setChatQuestion("How do I track and submit my assigned work as an engineer?")}>Guide me through engineer work tracking <ArrowRight size={14} /></button>
                </div>
              </div>
            )}
            {chatMessages.map((message, index) => (
              <div className={`chat-message chat-${message.role}`} key={`guide-${message.role}-${index}`}>
                <div className="chat-bubble">
                  {message.content}
                  {message.sources?.map((source) => (
                    <div className="citation-card" key={`${source.title}-${source.version}`}>
                      <BookOpen size={14} />
                      <span><strong>{source.title}</strong><small>Version {source.version} · Approved guidance</small><small>{source.excerpt}</small></span>
                      {source.source_url && <a href={source.source_url} target="_blank" rel="noreferrer">Source</a>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {chatLoading && <div className="typing-indicator"><i /><i /><i /> Preparing guidance…</div>}
          </div>
          <form className="chat-form assistant-widget-form" onSubmit={(event) => void sendQuestion(event)}>
            <input value={chatQuestion} onChange={(event) => setChatQuestion(event.target.value)} placeholder="Ask about schemes or engineer work..." aria-label="Ask NagarikSetu Guide" />
            <button className="send-button" disabled={chatLoading || !chatQuestion.trim()} aria-label="Send question"><Send size={17} /></button>
          </form>
          {!user && <p className="assistant-footnote">Sign in to chat. Official scheme links remain available without signing in.</p>}
          <p className="assistant-footnote"><ShieldCheck size={13} /> Guidance only; government officers make official decisions.</p>
        </section>
      )}
      <button
        className="assistant-widget-toggle"
        onClick={() => setAssistantOpen((open) => !open)}
        aria-label={assistantOpen ? "Close NagarikSetu Guide" : "Open NagarikSetu Guide"}
        aria-expanded={assistantOpen}
      >
        {assistantOpen ? <X size={20} /> : <Sparkles size={21} />}
        <span>AI</span>
      </button>

      {reportOpen && (
        <Modal
          title="Report a civic issue"
          subtitle="Share a little detail so the right team can take a look."
          onClose={() => setReportOpen(false)}
        >
          <form className="modal-form" onSubmit={(event) => void submitReport(event)}>
            <label>What needs attention?<input name="title" required minLength={8} maxLength={180} placeholder="e.g. Pothole near the bus stop" /></label>
            <label>Tell us more<textarea name="description" required minLength={12} maxLength={4000} placeholder="Describe the issue and how it affects your area..." rows={3} /></label>
            <div className="form-two-col">
              <label>Category<select name="category" required><option>Roads & pavements</option><option>Water & drainage</option><option>Street lighting</option><option>Waste management</option><option>Pollution & environment</option></select></label>
              <label>Your priority estimate<select name="severity"><option>Medium</option><option>Low</option><option>High</option><option>Critical</option></select></label>
            </div>
            <label>Take a photo with your camera<input name="files" type="file" accept="image/*" capture="environment" /><small>On supported phones, this opens the rear camera.</small></label>
            <label>Attach existing photos, videos, audio, or PDF<input name="files" type="file" multiple accept="image/jpeg,image/png,image/webp,image/heic,image/heif,video/mp4,video/quicktime,video/webm,audio/mpeg,audio/mp4,audio/ogg,audio/wav,audio/webm,application/pdf" /></label>
            <div className="modal-note"><ShieldCheck size={15} /> Up to 5 files, 20 MB each. NagarikSetu provides preliminary keyword-based triage only; an officer makes official decisions.</div>
            <label>Location<input name="address" required minLength={4} maxLength={240} placeholder="Street, neighborhood, landmark" /></label>
            <label>Ward<input name="ward" required minLength={2} maxLength={100} placeholder="Enter your ward or service area" /></label>
            <div className="coordinate-heading">
              <strong>Report coordinates</strong>
              <button type="button" className="button button-light button-small" onClick={() => void useCurrentLocationForReport()}>
                <LocateFixed size={14} /> Use current location
              </button>
            </div>
            <div className="form-two-col">
              <label>Latitude<input name="latitude" type="number" step="any" min="-90" max="90" required value={reportCoordinates.latitude} onChange={(event) => {setReportLocationEvidence(null);setReportCoordinates((current) => ({ ...current, latitude: event.target.value }));}} /></label>
              <label>Longitude<input name="longitude" type="number" step="any" min="-180" max="180" required value={reportCoordinates.longitude} onChange={(event) => {setReportLocationEvidence(null);setReportCoordinates((current) => ({ ...current, longitude: event.target.value }));}} /></label>
            </div>
            <div className="modal-note"><MapPin size={15} /> {reportLocationEvidence ? `Device-reported accuracy ±${Math.round(reportLocationEvidence.accuracy)} m · captured ${new Date(reportLocationEvidence.capturedAt).toLocaleString()}.` : "Choose a location to fill the coordinates, or enter them manually. Device location is collected only after you request it."}</div>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => setReportOpen(false)}>Cancel</button>
              <button className="button button-primary"><Send size={15} /> Submit report</button>
            </div>
          </form>
        </Modal>
      )}

      {engineerRegistrationOpen && (
        <Modal
          title="Apply as an engineer"
          subtitle="Verify your email first; an authorized officer must approve your professional registration."
          onClose={() => setEngineerRegistrationOpen(false)}
        >
          <form className="modal-form" onSubmit={(event) => void submitEngineerRegistration(event)}>
            <label>Full name<input name="name" required minLength={2} maxLength={120} autoComplete="name" /></label>
            <label>Email<input name="email" type="email" required minLength={6} maxLength={180} autoComplete="email" /></label>
            <label>Mobile number<input name="phone_number" type="tel" required minLength={7} maxLength={24} autoComplete="tel" /></label>
            <label>Password
              <span className="password-input-wrap">
                <input name="password" type={engineerPasswordVisible ? "text" : "password"} required minLength={12} maxLength={128} autoComplete="new-password" />
                <button type="button" className="password-visibility" onClick={() => setEngineerPasswordVisible((visible) => !visible)} aria-label={engineerPasswordVisible ? "Hide password" : "Show password"}>{engineerPasswordVisible ? <EyeOff size={16} /> : <Eye size={16} />}</button>
              </span>
            </label>
            <label>Confirm password<input name="confirm_password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>
            <label>Department<input name="department" required minLength={2} maxLength={100} placeholder="e.g. Public Works" /></label>
            <label>Professional registration number<input name="registration_number" required minLength={2} maxLength={100} /></label>
            <label>Skills, separated by commas<input name="skills" required placeholder="Road maintenance, surveying" /></label>
            <label>Application note<textarea name="application_note" required minLength={10} maxLength={2000} rows={3} placeholder="Share relevant experience and the scope of work you handle." /></label>
            <label className="terms-acceptance"><input name="terms_accepted" type="checkbox" required /> I accept the NagarikSetu terms and privacy notice.</label>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => setEngineerRegistrationOpen(false)}>Cancel</button>
              <button className="button button-primary"><Send size={15} /> Submit application</button>
            </div>
          </form>
        </Modal>
      )}

      {loginOpen && (
        <Modal
          title="Sign in to NagarikSetu"
          subtitle="Use the email and password registered with NagarikSetu."
          onClose={() => setLoginOpen(false)}
        >
          <form className="modal-form" onSubmit={(event) => void signIn(event)}>
            <div className="auth-create auth-create-top">
              <span>New to NagarikSetu?</span>
              <button type="button" className="text-button" onClick={() => {setLoginOpen(false);setCitizenRegistrationOpen(true);}}>Sign up for a citizen account</button>
            </div>
            {googleClientId && (
              <section className="google-signin-section" aria-label="Google sign-in">
                {!googleScriptLoaded && <p className="google-signin-status">Loading Google sign-in…</p>}
                <div className="google-signin-button" ref={googleButtonRef} />
              </section>
            )}
            <div className="auth-divider"><span>{googleClientId ? "or sign in with email" : "Sign in with email"}</span></div>
            <label>Email<input id="login-email" name="email" type="email" required minLength={6} maxLength={180} pattern="[^@ ]+@[^@ ]+\.[^@ ]+" title="Enter an email address such as name@example.com." autoComplete="username" value={loginEmail} onChange={(event) => {setLoginEmail(event.target.value);setLoginError("");}} /></label>
            <label>Password
              <span className="password-input-wrap">
                <input name="password" type={loginPasswordVisible ? "text" : "password"} required maxLength={128} autoComplete="current-password" value={loginPassword} onChange={(event) => {setLoginPassword(event.target.value);setLoginError("");}} />
                <button type="button" className="password-visibility" onClick={() => setLoginPasswordVisible((visible) => !visible)} aria-label={loginPasswordVisible ? "Hide password" : "Show password"}>{loginPasswordVisible ? <EyeOff size={16} /> : <Eye size={16} />}</button>
              </span>
            </label>
            <div className="auth-create">
              <button type="button" className="text-button" onClick={() => {setLoginOpen(false);setForgotPasswordOpen(true);}}>Forgot password?</button>
              <button type="button" className="text-button" onClick={() => void resendVerificationEmail()}>Resend verification email</button>
            </div>
            {loginError && <p className="auth-error" role="alert">{loginError}</p>}
            <div className="modal-note"><ShieldCheck size={15} /> Your account role and access are verified by NagarikSetu.</div>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => setLoginOpen(false)}>Cancel</button>
              <button className="button button-primary"><LogIn size={15} /> Sign in</button>
            </div>
          </form>
        </Modal>
      )}

      {citizenRegistrationOpen && (
        <Modal
          title="Create a NagarikSetu account"
          subtitle="Verify your email address before signing in."
          onClose={() => setCitizenRegistrationOpen(false)}
        >
          <form className="modal-form" onSubmit={(event) => void registerCitizen(event)}>
            <label>Full name<input name="name" required minLength={2} maxLength={120} autoComplete="name" /></label>
            <label>Email<input name="email" type="email" required minLength={6} maxLength={180} pattern="[^@ ]+@[^@ ]+\.[^@ ]+" title="Enter an email address such as name@example.com." autoComplete="email" /></label>
            <label>Mobile number<input name="phone_number" type="tel" required minLength={7} maxLength={24} autoComplete="tel" /></label>
            <label>Password
              <span className="password-input-wrap">
                <input name="password" type={registrationPasswordVisible ? "text" : "password"} required minLength={12} maxLength={128} autoComplete="new-password" />
                <button type="button" className="password-visibility" onClick={() => setRegistrationPasswordVisible((visible) => !visible)} aria-label={registrationPasswordVisible ? "Hide password" : "Show password"}>{registrationPasswordVisible ? <EyeOff size={16} /> : <Eye size={16} />}</button>
              </span>
              <small>Use a unique NagarikSetu password with at least 12 characters.</small>
            </label>
            <label>Confirm password<input name="confirm_password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>
            <label className="terms-acceptance"><input name="terms_accepted" type="checkbox" required /> I accept the NagarikSetu terms and privacy notice.</label>
            <div className="modal-note"><ShieldCheck size={15} /> Passwords are securely hashed. Email verification is required before login.</div>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => {setCitizenRegistrationOpen(false);setLoginOpen(true);}}>Back to sign in</button>
              <button className="button button-primary"><UserRoundPlus size={15} /> Create account</button>
            </div>
          </form>
        </Modal>
      )}

      {emailVerificationStatus && (
        <Modal
          title={emailVerificationStatus === "verifying" ? "Verifying email" : "Email verification"}
          subtitle="NagarikSetu account verification"
          onClose={() => setEmailVerificationStatus(null)}
        >
          <div className="verification-result" role="status">
            {emailVerificationStatus === "verifying" ? (
              <p>Checking your one-time verification link…</p>
            ) : emailVerificationStatus === "verified" ? (
              <>
                <CheckCircle2 size={26} />
                <p>Your email is verified. You can now sign in with your NagarikSetu password.</p>
                <button type="button" className="button button-primary" onClick={() => {setEmailVerificationStatus(null);setLoginOpen(true);}}>Continue to sign in</button>
              </>
            ) : (
              <>
                <p>This link could not be verified. It may have expired or already been used.</p>
                <button type="button" className="button button-primary" onClick={() => {setEmailVerificationStatus(null);setLoginOpen(true);}}>Go to sign in</button>
              </>
            )}
          </div>
        </Modal>
      )}

      {forgotPasswordOpen && (
        <Modal
          title="Forgot password"
          subtitle="We’ll send a one-time reset link to the email address on your account."
          onClose={() => setForgotPasswordOpen(false)}
        >
          <form className="modal-form" onSubmit={(event) => void requestPasswordReset(event)}>
            <label>Email<input name="email" type="email" required minLength={6} maxLength={180} defaultValue={loginEmail} autoComplete="email" /></label>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => {setForgotPasswordOpen(false);setLoginOpen(true);}}>Back to sign in</button>
              <button className="button button-primary">Send reset link</button>
            </div>
          </form>
        </Modal>
      )}

      {passwordResetOpen && (
        <Modal
          title="Reset password"
          subtitle="Choose a new NagarikSetu password. The reset link expires after 60 minutes."
          onClose={() => setPasswordResetOpen(false)}
        >
          <form className="modal-form" onSubmit={(event) => void resetPassword(event)}>
            <label>New password
              <span className="password-input-wrap">
                <input name="password" type={registrationPasswordVisible ? "text" : "password"} required minLength={12} maxLength={128} autoComplete="new-password" />
                <button type="button" className="password-visibility" onClick={() => setRegistrationPasswordVisible((visible) => !visible)} aria-label={registrationPasswordVisible ? "Hide password" : "Show password"}>{registrationPasswordVisible ? <EyeOff size={16} /> : <Eye size={16} />}</button>
              </span>
            </label>
            <label>Confirm new password<input name="confirm_password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => setPasswordResetOpen(false)}>Cancel</button>
              <button className="button button-primary">Update password</button>
            </div>
          </form>
        </Modal>
      )}

      {invitationAcceptOpen && (
        <Modal
          title="Activate official account"
          subtitle="Create a password and add your mobile number to finish account activation."
          onClose={() => setInvitationAcceptOpen(false)}
        >
          <form className="modal-form" onSubmit={(event) => void acceptOfficialInvitation(event)}>
            <label>Mobile number<input name="phone_number" type="tel" required minLength={7} maxLength={24} autoComplete="tel" /></label>
            <label>Password<input name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>
            <label>Confirm password<input name="confirm_password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>
            <label className="terms-acceptance"><input name="terms_accepted" type="checkbox" required /> I accept the NagarikSetu terms and privacy notice.</label>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => setInvitationAcceptOpen(false)}>Cancel</button>
              <button className="button button-primary">Activate account</button>
            </div>
          </form>
        </Modal>
      )}

      {profileOpen && (
        <Modal
          title="My profile"
          subtitle="Your permissions come from your verified NagarikSetu account role."
          onClose={() => setProfileOpen(false)}
        >
          {!profileData && !profileError && <p className="empty-state">Loading your profile…</p>}
          {profileError && <p className="auth-error" role="alert">{profileError}</p>}
          {profileData && (
            <form className="modal-form" onSubmit={(event) => void updateProfile(event)}>
              <label>Email<input value={profileData.email} readOnly /></label>
              <label>Role<input value={roleLabels[profileData.role]} readOnly /></label>
              {profileData.role === "citizen" ? (
                <>
                  <label>Full name<input name="name" defaultValue={profileData.name} required minLength={2} maxLength={120} autoComplete="name" /></label>
                  <label>Mobile number<input name="phone_number" defaultValue={profileData.phone_number} type="tel" required minLength={7} maxLength={24} autoComplete="tel" /></label>
                  <label>Address<input name="address" defaultValue={profileData.address ?? ""} maxLength={240} autoComplete="street-address" /></label>
                  <label>Ward or service area<input name="ward" defaultValue={profileData.ward ?? ""} maxLength={100} /></label>
                  <button className="button button-primary">Save profile</button>
                </>
              ) : (
                <>
                  <label>Full name<input value={profileData.name} readOnly /></label>
                  <label>Mobile number<input value={profileData.phone_number} readOnly /></label>
                  {profileData.official && (
                    <>
                      <label>Employee ID<input value={profileData.official.employee_id} readOnly /></label>
                      <label>Department<input value={profileData.official.department} readOnly /></label>
                      <label>Designation<input value={profileData.official.designation} readOnly /></label>
                      <label>Jurisdiction<input value={profileData.official.jurisdiction} readOnly /></label>
                    </>
                  )}
                  <div className="modal-note"><ShieldCheck size={15} /> Official details can only be changed by an authorized administrator.</div>
                </>
              )}
            </form>
          )}
        </Modal>
      )}

      {selectedWorkComplaint && (
        <Modal
          title="Submit completed work"
          subtitle={`${selectedWorkComplaint.reference} · ${selectedWorkComplaint.address}`}
          onClose={() => setSelectedWorkComplaint(null)}
        >
          <form className="modal-form" onSubmit={(event) => void submitWork(event)}>
            <input type="hidden" name="location_accuracy_meters" value={workLocationEvidence?.accuracy ?? ""} />
            <input type="hidden" name="location_captured_at" value={workLocationEvidence?.capturedAt ?? ""} />
            <label>Work completed<textarea name="work_details" required minLength={10} maxLength={4000} rows={3} placeholder="Describe the work performed." /></label>
            <label>Completion notes<textarea name="completion_notes" required minLength={10} maxLength={2000} rows={2} placeholder="Note any remaining issues or relevant details." /></label>
            <div className="form-two-col">
              <label>Before photo<input type="file" accept="image/*" capture="environment" required onChange={(event) => void selectWorkEvidence("before", event.target.files?.[0])} /></label>
              <label>After photo<input type="file" accept="image/*" capture="environment" required onChange={(event) => void selectWorkEvidence("after", event.target.files?.[0])} /></label>
            </div>
            <div className="evidence-images">
              {workEvidence.before && <EvidencePhoto label="Before" evidence={workEvidence.before} />}
              {workEvidence.after && <EvidencePhoto label="After" evidence={workEvidence.after} />}
            </div>
            {evidenceProcessing > 0 && <p className="evidence-processing">Preparing photos…</p>}
            <div className="form-two-col">
              <label>Latitude<input name="latitude" type="number" step="any" min="-90" max="90" required value={workCoordinates.latitude} onChange={(event) => {setWorkLocationEvidence(null);setWorkCoordinates((current) => ({ ...current, latitude: event.target.value }));}} /></label>
              <label>Longitude<input name="longitude" type="number" step="any" min="-180" max="180" required value={workCoordinates.longitude} onChange={(event) => {setWorkLocationEvidence(null);setWorkCoordinates((current) => ({ ...current, longitude: event.target.value }));}} /></label>
            </div>
            <button type="button" className="button button-light button-small" onClick={() => void useCurrentLocationForWork()}><LocateFixed size={14} /> Capture current work location</button>
            <label>Evidence capture time<input name="captured_at" type="datetime-local" required defaultValue={dateTimeLocalValue(new Date())} /></label>
            <p className="modal-note"><ShieldCheck size={15} /> {workLocationEvidence ? `Device-reported accuracy ±${Math.round(workLocationEvidence.accuracy)} m · captured ${new Date(workLocationEvidence.capturedAt).toLocaleString()}.` : "Use the button to capture GPS accuracy and timestamp, or keep the complaint coordinates as a manual estimate. Location is only collected after you request it."} GPS and browser timestamps are supporting evidence, not independently verified proof.</p>
            <div className="modal-actions">
              <button type="button" className="button button-light" onClick={() => setSelectedWorkComplaint(null)}>Cancel</button>
              <button className="button button-primary" disabled={evidenceProcessing > 0}><Send size={15} /> Submit for review</button>
            </div>
          </form>
        </Modal>
      )}

      {historyComplaint && (
        <Modal
          title="Work & verification history"
          subtitle={`${historyComplaint.reference} · ${historyComplaint.title}`}
          onClose={() => setHistoryComplaint(null)}
        >
          {complaintAttachments.length > 0 && (
            <section className="complaint-attachment-list" aria-label="Citizen report evidence">
              <strong>Citizen report evidence</strong>
              {complaintAttachments.map((attachment) => (
                <div key={attachment.id}>
                  <span>{attachment.original_name}<small>{(attachment.size_bytes / (1024 * 1024)).toFixed(2)} MB · {attachment.content_type}</small></span>
                  <button type="button" className="text-button" onClick={() => void downloadComplaintAttachment(attachment)}>Download</button>
                </div>
              ))}
            </section>
          )}
          <ol className="work-timeline">
            {workHistory.map((item, index) => (
              <li key={`${item.created_at}-${index}`}>
                <span className="timeline-dot"><CheckCircle2 size={13} /></span>
                <div>
                  <strong>{statusLabel(item.event_type)}{item.attempt_number ? ` · Attempt ${item.attempt_number}` : ""}</strong>
                  <small>{item.actor} · {new Date(item.created_at).toLocaleString()}</small>
                  <p>{item.note}</p>
                  {item.latitude != null && item.longitude != null && <small>Recorded coordinates: {item.latitude.toFixed(5)}, {item.longitude.toFixed(5)}</small>}
                  {(item.before_evidence || item.after_evidence) && (
                    <div className="evidence-images">
                      <EvidencePhoto label="Before" evidence={item.before_evidence ?? ""} />
                      <EvidencePhoto label="After" evidence={item.after_evidence ?? ""} />
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ol>
          {workHistory.length === 0 && <p className="empty-state">No assignment or work updates have been recorded yet.</p>}
          {user?.role === "citizen" && ["CLOSED", "OFFICIALLY_COMPLETED"].includes(historyComplaint.official_status) && (
            citizenFeedback ? (
              <div className="modal-note" role="status">
                <CheckCircle2 size={15} /> Your {citizenFeedback.rating}/5 closure feedback was recorded.
              </div>
            ) : (
              <form className="modal-form closure-feedback-form" onSubmit={(event) => void submitFeedback(event)}>
                <strong>How was this issue resolved?</strong>
                <label>Rating<select name="rating" defaultValue="5"><option value="5">5 — Excellent</option><option value="4">4 — Good</option><option value="3">3 — Fair</option><option value="2">2 — Poor</option><option value="1">1 — Very poor</option></select></label>
                <label>Optional comment<textarea name="comment" maxLength={2000} rows={2} placeholder="Share a brief note about the outcome..." /></label>
                <button className="button button-primary" disabled={feedbackSubmitting}>
                  <Send size={15} /> {feedbackSubmitting ? "Submitting…" : "Submit feedback"}
                </button>
              </form>
            )
          )}
        </Modal>
      )}

      {selectedReview && (
        <Modal
          title="Review work evidence"
          subtitle={`${selectedReview.complaint.reference} · ${selectedReview.complaint.address}`}
          onClose={() => setSelectedReview(null)}
        >
          <div className="review-modal-detail">
            <div className="review-evidence expanded">
              <span><FileCheck2 size={18} /><b>Before</b><small>{selectedReview.submission.before_evidence.startsWith("data:image/") ? "Engineer photo" : selectedReview.submission.before_evidence}</small></span>
              <ArrowRight size={17} />
              <span><CheckCircle2 size={18} /><b>After</b><small>{selectedReview.submission.after_evidence.startsWith("data:image/") ? "Engineer photo" : selectedReview.submission.after_evidence}</small></span>
            </div>
            <div className="evidence-images">
              <EvidencePhoto label="Before" evidence={selectedReview.submission.before_evidence} />
              <EvidencePhoto label="After" evidence={selectedReview.submission.after_evidence} />
            </div>
            <p><b>Work details</b><br />{selectedReview.submission.work_details}</p>
            <p><b>Engineer notes</b><br />{selectedReview.submission.completion_notes}</p>
            <div className="verification-gps-summary">
              <p><MapPin size={14} /> Complaint: {selectedReview.complaint.latitude.toFixed(5)}, {selectedReview.complaint.longitude.toFixed(5)}</p>
              <p><MapPin size={14} /> Work: {selectedReview.submission.latitude.toFixed(5)}, {selectedReview.submission.longitude.toFixed(5)}</p>
              <p>Distance between locations: {Math.round(selectedReview.submission.distance_from_complaint_meters)} m</p>
              <p>Reported location accuracy: {selectedReview.complaint.location_accuracy_meters == null ? "Not captured" : `±${Math.round(selectedReview.complaint.location_accuracy_meters)} m`}</p>
              <p>GPS accuracy: {selectedReview.submission.location_accuracy_meters == null ? "Not captured" : `±${Math.round(selectedReview.submission.location_accuracy_meters)} m`}</p>
              <p>Reported location captured: {selectedReview.complaint.location_captured_at ? new Date(selectedReview.complaint.location_captured_at).toLocaleString() : "Not captured"}</p>
              <p>GPS captured: {selectedReview.submission.location_captured_at ? new Date(selectedReview.submission.location_captured_at).toLocaleString() : "Not captured"}</p>
              {selectedReview.submission.distance_review_flag && (
                <p className="gps-review-warning" role="status">This submission is over 500 m from the reported complaint location. Review the evidence; this is a flag, not an automatic rejection.</p>
              )}
            </div>
            <VerificationLocationMap complaint={selectedReview.complaint} submission={selectedReview.submission} />
            <p className="gps-note"><ShieldCheck size={14} /> Browser GPS and client timestamps are supporting evidence, not independently verified proof of presence.</p>
            <form className="modal-form" onSubmit={(event) => void decideReview(event)}>
              <label>Decision<select name="decision"><option value="APPROVED">Approve work</option><option value="REJECTED">Request rework</option></select></label>
              <label>Reason / review notes<textarea name="reason" required minLength={8} maxLength={2000} rows={3} placeholder="Record your review rationale. This will be saved." /></label>
              <div className="modal-actions">
                <button type="button" className="button button-light" onClick={() => setSelectedReview(null)}>Cancel</button>
                <button className="button button-primary"><ShieldCheck size={15} /> Record decision</button>
              </div>
            </form>
          </div>
        </Modal>
      )}

      {toast && <div className="toast-message" role="status"><CheckCircle2 size={17} /> {toast}<button onClick={() => setToast("")} aria-label="Dismiss"><X size={15} /></button></div>}
    </div>
  );
}

function MetricCard({ title, value, change, icon: Icon, tone }: { title: string; value: number; change: string; icon: typeof FileCheck2; tone: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{title}</span><span className={`metric-icon metric-${tone}`}><Icon size={17} /></span></div><div className="metric-value">{String(value).padStart(2, "0")}</div><div className="metric-change"><span className={tone === "red" || tone === "orange" ? "change-neutral" : "change-positive"}>{tone === "red" ? <ArrowUpRight size={14} /> : tone === "blue" ? <ArrowDownRight size={14} /> : null}{change}</span></div></article>;
}

function AttentionItem({ complaint }: { complaint: Complaint }) {
  return <div className="attention-item"><span className={`attention-icon attention-${complaint.severity.toLowerCase()}`}><MapPin size={16} /></span><span className="attention-copy"><strong>{complaint.title}</strong><small>{complaint.ward} <i>·</i> {complaint.reference}</small></span><span className={severityClass(complaint.severity)}>{complaint.severity}</span></div>;
}

function ComplaintTable({ complaints, onSelect }: { complaints: Complaint[]; onSelect?: (complaint: Complaint) => void }) {
  return <div className="table-scroll"><table className="complaint-table"><thead><tr><th>REPORT</th><th>CATEGORY</th><th>PRIORITY</th><th>STATUS</th><th>LOCATION</th>{onSelect && <th />}</tr></thead><tbody>{complaints.map((complaint) => <tr key={complaint.id}><td><span className="table-title">{complaint.title}</span><small>{complaint.reference}</small>{complaint.assessment && <small>Preliminary suggestion: {complaint.assessment.suggested_severity} · {complaint.assessment.suggested_category} · {complaint.assessment.suggested_department}</small>}</td><td><span className="category-cell">{complaint.category}</span></td><td><span className={severityClass(complaint.severity)}><i className="severity-dot" />{complaint.severity}</span></td><td><StatusBadge status={complaint.official_status} /></td><td><span className="location-cell"><MapPin size={13} />{complaint.ward.split(" · ")[0]}</span></td>{onSelect && <td><button className="row-action" aria-label={`View work history for ${complaint.reference}`} onClick={() => onSelect(complaint)}><ArrowRight size={15} /></button></td>}</tr>)}</tbody></table></div>;
}

function StatusBadge({ status }: { status: string }) {
  const className = status === "OFFICIALLY_COMPLETED" || status === "CLOSED" ? "status-complete" : status === "AWAITING_VERIFICATION" ? "status-review" : status === "IN_PROGRESS" ? "status-progress" : "status-assigned";
  return <span className={`status-badge ${className}`}><i />{statusLabel(status)}</span>;
}

function EvidencePhoto({ label, evidence }: { label: string; evidence: string }) {
  if (!evidence.startsWith("data:image/jpeg;base64,")) return null;
  return <figure className="evidence-photo"><img src={evidence} alt={`${label} photo submitted by the engineer`} /><figcaption>{label} photo</figcaption></figure>;
}

function ComplaintMap({ complaints, compact = false }: { complaints: Complaint[]; compact?: boolean }) {
  return <div className={`map-canvas ${compact ? "map-compact" : ""}`}><MapContainer center={DEFAULT_MAP_CENTER} zoom={12} scrollWheelZoom={false} zoomControl><TileLayer attribution='Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community' url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" />{complaints.map((item) => <CircleMarker key={item.id} center={[item.latitude, item.longitude]} radius={item.severity === "Critical" ? 9 : 7} pathOptions={{ color: "#fff", weight: 2, fillColor: item.severity === "Critical" ? "#dc655a" : item.severity === "High" ? "#e59a48" : item.severity === "Medium" ? "#6396c1" : "#6e9a80", fillOpacity: 0.94 }}><Popup><strong>{item.reference} · {item.title}</strong><br />{item.address}<br />{statusLabel(item.official_status)}</Popup></CircleMarker>)}</MapContainer></div>;
}

function VerificationLocationMap({ complaint, submission }: { complaint: Complaint; submission: VerificationItem["submission"] }) {
  const bounds: [[number, number], [number, number]] = [
    [complaint.latitude, complaint.longitude],
    [submission.latitude, submission.longitude],
  ];
  return (
    <div className="map-canvas verification-location-map">
      <MapContainer bounds={bounds} boundsOptions={{ padding: [24, 24], maxZoom: 15 }} scrollWheelZoom={false} zoomControl>
        <TileLayer attribution='Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community' url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" />
        <Polyline positions={bounds} pathOptions={{ color: "#f0a24f", weight: 3, dashArray: "6 6" }} />
        <CircleMarker center={bounds[0]} radius={8} pathOptions={{ color: "#fff", weight: 2, fillColor: "#4c8db5", fillOpacity: 1 }}>
          <Popup>Complaint location · {complaint.reference}</Popup>
        </CircleMarker>
        <CircleMarker center={bounds[1]} radius={8} pathOptions={{ color: "#fff", weight: 2, fillColor: "#4b9b68", fillOpacity: 1 }}>
          <Popup>Work submission location</Popup>
        </CircleMarker>
      </MapContainer>
    </div>
  );
}

function Modal({ title, subtitle, onClose, children }: { title: string; subtitle: string; onClose: () => void; children: React.ReactNode }) {
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="modal-card" role="dialog" aria-modal="true" aria-label={title}><div className="modal-heading"><div><h2>{title}</h2><p>{subtitle}</p></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={19} /></button></div>{children}</section></div>;
}

export default App;
