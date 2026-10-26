"use client";

import { useEffect, useRef, useState } from "react";
import { api, settings as loadSettings, waitForJob } from "@/lib/api";
import type { Connections, Settings, VoiceClip } from "@/lib/types";
import {
  Banner,
  BannerContent,
  Button,
  Checkbox,
  Flag,
  FlagContent,
  Input,
  InputContainer,
  InputMessage,
  Label,
  Radio,
  Select,
  Textarea,
  Typography,
} from "@/ui";

const VOICE_CHOICES = [
  { id: "kokoro_british", title: "Kokoro British", detail: "bf_emma and bm_george. Lang code b." },
  { id: "kokoro_american", title: "Kokoro American", detail: "af_bella and am_michael. Lang code a." },
  { id: "dia", title: "Dia expressive", detail: "Two-host dialogue, with light emotion." },
  { id: "my_voice", title: "My voice", detail: "Your clip for one host. The other stays a stock Dia voice." },
];

export default function SettingsPage() {
  const [form, setForm] = useState<Settings | null>(null);
  const [connections, setConnections] = useState<Connections | null>(null);
  const [mcp, setMcp] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clip, setClip] = useState<VoiceClip | null>(null);
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const previewRef = useRef<HTMLAudioElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);

  useEffect(() => {
    loadSettings()
      .then((value) => {
        setForm(value);
        setMcp((value.mcp_mail_urls || []).join("\n"));
      })
      .catch((err: Error) => setError(err.message));
    api<Connections>("/api/connections").then(setConnections).catch(() => setConnections(null));
    loadClip();
  }, []);

  function loadClip() {
    api<VoiceClip>("/api/voice/mine").then(setClip).catch(() => setClip(null));
  }

  function patch(partial: Partial<Settings>) {
    setForm((current) => (current ? { ...current, ...partial } : current));
  }

  async function save() {
    if (!form) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await api<Settings>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          mcp_mail_urls: mcp.split(/\n|,/).map((item) => item.trim()).filter(Boolean),
        }),
      });
      setForm(saved);
      setMessage("Saved on this machine. The next podcast uses these settings.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save. Check the values and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(path: string) {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: "POST" });
      setConnections(await api<Connections>("/api/connections"));
      setMessage("Disconnected on this machine. The provider has not revoked the grant.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect.");
    } finally {
      setBusy(false);
    }
  }

  async function sync(path: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ inserted: number }>(path, { method: "POST" });
      setMessage(`Imported ${result.inserted} message(s). Home shows each topic once.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The mailbox could not be read.");
    } finally {
      setBusy(false);
    }
  }

  async function preview(id: string) {
    const audio = previewRef.current;
    if (!audio) return;
    if (previewing === id && !audio.paused) {
      audio.pause();
      setPreviewing(null);
      return;
    }
    audio.src = id === "my_voice" ? "/api/voice/mine/audio" : `/api/voices/preview/${id}`;
    try {
      await audio.play();
      setPreviewing(id);
    } catch {
      setPreviewing(null);
      setError("The preview could not play. Check that the clip is on this machine.");
    }
  }

  async function storeClip(file: Blob, name: string) {
    if (!consent) {
      setError("Confirm that this is your own voice before saving the clip.");
      return;
    }
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file, name);
      body.append("consent", "true");
      body.append("host", form.my_voice_host);
      const saved = await api<VoiceClip>("/api/voice/mine", { method: "POST", body });
      setClip(saved);
      setMessage("Clip stored on this machine. Save settings to use it on the next podcast.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The clip could not be stored.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleRecording() {
    if (recording && recorderRef.current) {
      recorderRef.current.stop();
      return;
    }
    if (!consent) {
      setError("Confirm that this is your own voice before recording.");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser has no microphone. Upload a clip instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : undefined;
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      const parts: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) parts.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        void storeClip(new Blob(parts, { type: recorder.mimeType || "audio/webm" }), "my-voice.webm");
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setError("The browser did not allow the microphone. You can upload a clip instead.");
    }
  }

  async function removeClip() {
    setBusy(true);
    try {
      await api("/api/voice/mine", { method: "DELETE" });
      setConsent(false);
      loadClip();
      setMessage("The voice clip was deleted from this machine.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The clip could not be deleted.");
    } finally {
      setBusy(false);
    }
  }

  if (!form) {
    return (
      <div className="page-frame reading-column">
        <Typography variant="body-2" tag="p" role="status">
          {error ? error : "Loading settings…"}
        </Typography>
      </div>
    );
  }

  return (
    <div className="page-frame fade-up reading-column stack-24">
      <div>
        <Typography variant="overline" tag="p">
          Setup
        </Typography>
        <Typography variant="headline-1" tag="h1" className="v-pt-8">
          Connections, model, voice
        </Typography>
        <Typography variant="body-2" colorScheme="subtle" tag="p" className="v-pt-12">
          Mail is read only. A cloud model is used only after you save a key here.
        </Typography>
      </div>
      {message ? (
        <Flag messageType="success">
          <FlagContent>{message}</FlagContent>
        </Flag>
      ) : null}
      {error ? (
        <Banner messageType="error">
          <BannerContent>{error}</BannerContent>
        </Banner>
      ) : null}

      <section className="hairline-card" style={{ padding: 24 }} aria-label="Connections">
        <Typography variant="headline-4" tag="h2">
          Connections
        </Typography>
        <div className="stack-16 v-pt-16">
          <Connection
            title="Gmail"
            detail={connections?.gmail.connected ? connections.gmail.account : "Read-only Gmail API."}
            href={connections?.gmail.configured ? "/api/connect/gmail" : undefined}
            hint={connections?.gmail.configured ? "" : "Set INBOX_BRIEF_GOOGLE_CLIENT_ID and INBOX_BRIEF_GOOGLE_CLIENT_SECRET."}
            onSync={connections?.gmail.connected ? () => void sync("/api/connect/gmail/sync") : undefined}
            onDisconnect={connections?.gmail.connected ? () => void disconnect("/api/connect/gmail/disconnect") : undefined}
            busy={busy}
          />
          <Connection
            title="Outlook"
            detail={connections?.outlook.connected ? connections.outlook.account : "Read-only Microsoft Graph."}
            href={connections?.outlook.configured ? "/api/connect/outlook" : undefined}
            hint={connections?.outlook.configured ? "" : "Set INBOX_BRIEF_MICROSOFT_CLIENT_ID and INBOX_BRIEF_MICROSOFT_CLIENT_SECRET."}
            onSync={connections?.outlook.connected ? () => void sync("/api/connect/outlook/sync") : undefined}
            onDisconnect={connections?.outlook.connected ? () => void disconnect("/api/connect/outlook/disconnect") : undefined}
            busy={busy}
          />
          <Field
            id="mcp"
            label="MCP mail servers"
            hint="One server per line. An http line is streamable HTTP. A stdio: line runs a local program. Gmail: stdio:npx -y @gongrzhe/server-gmail-autoauth-mcp (search_emails, read_email). Outlook: stdio:npx -y @softeria/ms-365-mcp-server (list-mail-messages, get-mail-message). list_messages still works."
          >
            <Textarea id="mcp" value={mcp} onChange={(event) => setMcp(event.target.value)} placeholder={"http://127.0.0.1:3000/mcp\nstdio:npx -y @gongrzhe/server-gmail-autoauth-mcp"} />
          </Field>
          <Button type="button" colorScheme="secondary" disabled={busy || !mcp.trim()} onClick={() => void sync("/api/connect/mcp/sync")}>
            Sync MCP mail
          </Button>
          <Typography variant="subtitle-2" tag="h3">
            IMAP fallback
          </Typography>
          <div className="field-grid-2">
            <Field id="imap-host" label="Host">
              <Input id="imap-host" value={form.imap_host} onChange={(event) => patch({ imap_host: event.target.value })} />
            </Field>
            <Field id="imap-port" label="Port">
              <Input id="imap-port" type="number" value={form.imap_port} onChange={(event) => patch({ imap_port: Number(event.target.value) })} />
            </Field>
          </div>
          <Field id="imap-user" label="Username">
            <Input id="imap-user" value={form.imap_user} onChange={(event) => patch({ imap_user: event.target.value })} />
          </Field>
          <Field id="imap-password" label="App password" hint={form.imap_password_set ? "A password is saved. Leave this blank to keep it." : "Stored only on this machine."}>
            <Input id="imap-password" type="password" autoComplete="new-password" value={form.imap_password} onChange={(event) => patch({ imap_password: event.target.value })} />
          </Field>
          <Button type="button" colorScheme="secondary" disabled={busy} onClick={() => void pullImap()}>
            Pull IMAP
          </Button>
          <Field id="upload" label="Upload .eml or .mbox">
            <Input
              id="upload"
              type="file"
              accept=".eml,.mbox,message/rfc822"
              multiple
              onChange={(event) => void uploadFiles(event.target.files)}
            />
          </Field>
        </div>
      </section>

      <section className="hairline-card" style={{ padding: 24 }} aria-label="Model">
        <Typography variant="headline-4" tag="h2">
          Model
        </Typography>
        <div className="stack-16 v-pt-16">
          <Field id="provider" label="Provider">
            <Select id="provider" value={form.llm_provider} onChange={(event) => patch({ llm_provider: event.target.value })}>
              <option value="ollama">Ollama, on this machine</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="compatible">OpenAI-compatible server</option>
            </Select>
          </Field>
          <Field id="llm-model" label="Model name" hint="Leave blank to use the provider default. Ollama uses the script model.">
            <Input id="llm-model" value={form.llm_model} onChange={(event) => patch({ llm_model: event.target.value })} />
          </Field>
          {form.llm_provider === "compatible" || form.llm_provider === "openai" ? (
            <Field id="llm-base" label="Base URL" hint="OpenAI can stay blank. A compatible server needs its /v1 URL.">
              <Input id="llm-base" value={form.llm_base_url} onChange={(event) => patch({ llm_base_url: event.target.value })} />
            </Field>
          ) : null}
          {form.llm_provider !== "ollama" ? (
            <Field id="llm-key" label="API key" hint={form.llm_api_key_set ? "A key is saved. Leave this blank to keep it." : "Stored encrypted on this machine. It is not shown again."}>
              <Input id="llm-key" type="password" autoComplete="new-password" value={form.llm_api_key} onChange={(event) => patch({ llm_api_key: event.target.value })} />
            </Field>
          ) : null}
        </div>
      </section>

      <section className="hairline-card" style={{ padding: 24 }} aria-label="Voice">
        <Typography variant="headline-4" tag="h2">
          Voice
        </Typography>
        <Typography variant="body-3" colorScheme="subtle" tag="p" className="v-pt-8">
          Preview plays the bundled clip. My voice stays on this machine.
        </Typography>
        <div className="v-pt-8" role="radiogroup" aria-label="Voice engine and accent">
          {VOICE_CHOICES.map((choice) => (
            <div className="voice-option" key={choice.id}>
              <Radio id={`voice-${choice.id}`} name="voice-preset" value={choice.id} checked={form.voice_preset === choice.id} onChange={() => patch({ voice_preset: choice.id })} />
              <Label htmlFor={`voice-${choice.id}`}>
                {choice.title}
                <Typography variant="body-3" colorScheme="subtle" tag="span" className="v-pl-8">
                  {choice.detail}
                </Typography>
              </Label>
              <Button type="button" className="touch-44" colorScheme="tertiary" disabled={choice.id === "my_voice" && !clip?.has_clip} onClick={() => void preview(choice.id)}>
                {previewing === choice.id ? "Stop" : "Preview"}
              </Button>
            </div>
          ))}
        </div>
        <audio ref={previewRef} onEnded={() => setPreviewing(null)} />
        {form.voice_preset === "my_voice" ? (
          <div className="stack-16 v-pt-16">
            <Typography variant="body-2" tag="p">
              Record or upload 5 to 10 seconds of your own voice. Use a quiet room, 16 kHz or higher, and no music.
            </Typography>
            <blockquote className="voice-script">
              <Typography variant="body-2" tag="p">
                {clip?.script ?? "This is my voice for PodcastBox. I recorded it myself, in a quiet room, for use as one host."}
              </Typography>
            </blockquote>
            <Field id="my-host" label="Which host uses your voice">
              <Select id="my-host" value={form.my_voice_host} onChange={(event) => patch({ my_voice_host: event.target.value })}>
                <option value="S1">Mina</option>
                <option value="S2">Owen</option>
              </Select>
            </Field>
            <Label htmlFor="consent">This is my own voice. I agree to store this clip on this machine and to use it only as a host in my podcasts.</Label>
            <Checkbox id="consent" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <div className="ask-row">
              <Button type="button" className="touch-44" colorScheme="secondary" disabled={busy} onClick={() => void toggleRecording()}>
                {recording ? "Stop recording" : "Record"}
              </Button>
              <Button type="button" className="touch-44" colorScheme="tertiary" disabled={busy} onClick={() => document.getElementById("voice-file")?.click()}>
                Upload a clip
              </Button>
              {clip?.has_clip ? (
                <Button type="button" className="touch-44" colorScheme="tertiary" destructive disabled={busy} onClick={() => void removeClip()}>
                  Delete clip
                </Button>
              ) : null}
            </div>
            <input id="voice-file" hidden type="file" accept="audio/*,.wav,.mp3,.m4a,.webm,.ogg,.flac" onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void storeClip(file, file.name);
            }} />
            <Typography variant="body-3" colorScheme="subtle" tag="p" role="status">
              {clip?.has_clip ? `Stored on this machine. ${clip.duration_s} seconds, recorded at ${clip.original_sample_rate} Hz.` : "No clip stored on this machine."}
            </Typography>
          </div>
        ) : null}
      </section>

      <section className="hairline-card" style={{ padding: 24 }}>
        <Typography variant="headline-4" tag="h2">
          Review period
        </Typography>
        <Typography variant="body-3" colorScheme="subtle" tag="p" className="v-pt-8">
          A chain appears once in this window, not once per message.
        </Typography>
        <div className="stack-16 v-pt-16">
          <Field id="period" label="Window">
            <Select id="period" value={form.review_period} onChange={(event) => patch({ review_period: event.target.value })}>
              <option value="day">Today</option>
              <option value="week">This week</option>
              <option value="month">This month</option>
            </Select>
          </Field>
          <Field id="timezone" label="Timezone" hint="A podcast stays on Home until midnight in this timezone, then moves to the Library.">
            <Select id="timezone" value={form.timezone} onChange={(event) => patch({ timezone: event.target.value })}>
              {timezoneOptions(form.timezone).map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </section>

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button className="touch-44" disabled={busy} onClick={() => void save()}>
          {busy ? "Working…" : "Save settings"}
        </Button>
      </div>
    </div>
  );

  async function pullImap() {
    setBusy(true);
    setError(null);
    try {
      const started = await api<{ job_id: string }>("/api/ingest/imap", { method: "POST" });
      const job = await waitForJob(started.job_id);
      if (job.status === "error") throw new Error(job.error || "IMAP pull failed.");
      setMessage(job.error || "Mailbox checked.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "IMAP pull failed.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      Array.from(files).forEach((file) => body.append("files", file));
      const result = await api<{ inserted: number }>("/api/ingest/upload", { method: "POST", body });
      setMessage(`Added ${result.inserted} message(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed. Use .eml or .mbox files.");
    } finally {
      setBusy(false);
    }
  }
}

function Connection({ title, detail, href, hint, onSync, onDisconnect, busy }: { title: string; detail: string; href?: string; hint?: string; onSync?: () => void; onDisconnect?: () => void; busy: boolean }) {
  return (
    <div className="stack-8">
      <Typography variant="subtitle-2" tag="h3">
        {title}
      </Typography>
      <Typography variant="body-3" colorScheme="subtle" tag="p">
        {detail}
      </Typography>
      {hint ? (
        <Typography variant="body-3" tag="p">
          {hint}
        </Typography>
      ) : null}
      <div className="ask-row">
        {href ? (
          <Button colorScheme="secondary" element={<a href={href} />}>
            Connect {title}
          </Button>
        ) : null}
        {onSync ? (
          <Button colorScheme="tertiary" disabled={busy} onClick={onSync}>
            Sync
          </Button>
        ) : null}
        {onDisconnect ? (
          <Button colorScheme="tertiary" disabled={busy} onClick={onDisconnect}>
            Disconnect
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function timezoneOptions(current: string) {
  const zones = ["Europe/London", "Europe/Paris", "UTC", "America/New_York", "America/Los_Angeles", "Asia/Tokyo", "Australia/Sydney"];
  if (current && !zones.includes(current)) zones.unshift(current);
  return zones;
}

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="stack-8">
      <Label htmlFor={id}>{label}</Label>
      <InputContainer>{children}</InputContainer>
      {hint ? <InputMessage id={`${id}-hint`}>{hint}</InputMessage> : null}
    </div>
  );
}
