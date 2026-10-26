export type Segment = {
  id: string;
  position: number;
  speaker: "S1" | "S2";
  speaker_name: string;
  text: string;
  delivery: string;
  nonverbal: string | null;
  exaggeration: number;
  source_ids: string[];
  start_ms: number;
  end_ms: number;
};

export type Episode = {
  id: string;
  title: string;
  brief_date: string;
  status: string;
  error: string | null;
  engine: string | null;
  script_model: string | null;
  audio_mime: string | null;
  has_audio: boolean;
  duration_ms: number;
  created_at: string;
  is_sample: boolean;
  chain_id?: string | null;
  question?: string | null;
  style?: string | null;
  length?: string | null;
  segments?: Segment[];
  notes?: string[];
};

export type Mail = {
  id: string;
  message_id: string | null;
  thread_id: string | null;
  from_name: string;
  from_addr: string;
  to_addr: string;
  subject: string;
  date: string;
  source: string;
  is_noise: boolean;
  noise_reason: string | null;
  clean_body: string;
  raw_body?: string;
};

export type Settings = {
  timezone: string;
  schedule_enabled: boolean;
  schedule_time: string;
  window_hours: number;
  tts_engine: string;
  tts_fallback: string;
  dia_seed: number;
  kokoro_lang: string;
  kokoro_voice_s1: string;
  kokoro_voice_s2: string;
  voice_preset: string;
  my_voice_host: string;
  script_backend: string;
  script_model: string;
  script_model_fallback: string;
  drop_newsletters: boolean;
  drop_noreply: boolean;
  extra_noise_patterns: string[];
  imap_host: string;
  imap_port: number;
  imap_user: string;
  imap_password: string;
  imap_password_set: boolean;
  imap_folder: string;
  imap_ssl: boolean;
  llm_provider: string;
  llm_base_url: string;
  llm_model: string;
  llm_api_key: string;
  llm_api_key_set: boolean;
  review_period: string;
  mcp_mail_urls: string[];
};

export type Participant = { name: string; addr: string };

export type OverviewStatus = {
  email_count: number;
  chain_count: number;
  generated: boolean;
  episode_id: string | null;
  new_count: number;
  period_label: string;
  has_prior: boolean;
};

export type Chain = {
  id: string;
  title: string;
  reason: string;
  recommended: boolean;
  participants: Participant[];
  message_ids: string[];
  message_count: number;
  date_start: string;
  date_end: string;
  project: string;
  covered?: boolean;
  new_count?: number;
  new_since?: string;
  new_label?: string;
};

export type DayGroup = {
  date: string;
  label: string;
  count: number;
  podcasts: Episode[];
};

export type Connections = {
  gmail: { configured: boolean; connected: boolean; account: string; redirect_uri: string };
  outlook: { configured: boolean; connected: boolean; account: string; redirect_uri: string };
  imap: { configured: boolean };
  mcp: { urls: string[] };
  upload: { available: boolean };
};

export type VoiceClip = {
  script: string;
  host: string;
  has_clip: boolean;
  duration_s: number | null;
  sample_rate: number | null;
  original_sample_rate: number | null;
  consented_at: string | null;
  guidance: string[];
};

export type Job = {
  id: string;
  kind: string;
  status: string;
  error: string | null;
  episode_id: string | null;
};

export type SystemStatus = {
  dia: { ok?: boolean; device?: string | null; loaded?: boolean; model?: string };
  speaches: { ok: boolean };
  kokoro_onnx: { ok: boolean };
  ollama: { ok: boolean; models: string[]; error?: string };
  resolved_engine: string;
  script_backend: string;
  script_model: string;
};
