"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, episode as loadEpisode, messages, today, waitForJob } from "@/lib/api";
import type { Episode, Mail } from "@/lib/types";
import {
  Avatar,
  Banner,
  BannerContent,
  Button,
  Flag,
  FlagContent,
  Link as NovaLink,
  Typography,
  Utility,
} from "@/ui";
import { ChevronRight, Pause, Play } from "lucide-react";

function clock(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function when(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

const deliveryLabel: Record<string, string> = {
  warm: "warm",
  steady: "steady",
  curious: "curious",
  emphasis: "measured",
};

export function Brief({ episodeId }: { episodeId?: string }) {
  const [episode, setEpisode] = useState<Episode | null | undefined>(undefined);
  const [mail, setMail] = useState<Record<string, Mail>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function refresh() {
    setError(null);
    try {
      const loaded = episodeId ? await loadEpisode(episodeId) : (await today()).episode;
      setEpisode(loaded);
      const library = await messages(true);
      setMail(Object.fromEntries(library.messages.map((item) => [item.id, item])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The brief could not be loaded.");
      setEpisode(null);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episodeId]);

  const active = useMemo(() => {
    if (!episode?.segments) return -1;
    const ms = time * 1000;
    return episode.segments.findIndex((segment, index) => {
      const end = index === episode.segments!.length - 1 ? segment.end_ms + 400 : segment.end_ms;
      return ms >= segment.start_ms && ms < end;
    });
  }, [episode, time]);

  useEffect(() => {
    const node = document.getElementById(`segment-${active}`);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    node?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }, [active]);

  async function generate(scope: "window" | "all") {
    setBusy(scope === "all" ? "Reading the whole mailbox…" : "Reading the last window…");
    setError(null);
    try {
      const started = await api<{ job_id: string }>(`/api/episodes/generate?scope=${scope}`, { method: "POST" });
      const job = await waitForJob(started.job_id);
      if (job.status === "error") throw new Error(job.error || "The brief failed.");
      if (job.episode_id) {
        window.location.href = `/editions/${job.episode_id}`;
        return;
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The brief failed.");
    } finally {
      setBusy(null);
    }
  }

  if (episode === undefined) {
    return (
      <div className="page-frame fade-up">
        <Typography variant="body-2" colorScheme="subtle" tag="p" role="status">
          Loading the brief…
        </Typography>
      </div>
    );
  }

  return (
    <div className="page-frame fade-up">
      <div className="brief-layout">
        <article className="stack-24">
          {error ? (
            <Banner messageType="error">
              <BannerContent>{error} Refresh the page to try again.</BannerContent>
            </Banner>
          ) : null}
          {!episode ? (
            <Empty onGenerate={generate} busy={busy} />
          ) : (
            <>
              <div>
                <Typography variant="overline" tag="p">
                  {when(episode.brief_date)}
                </Typography>
                <Typography variant="headline-1" tag="h1" className="v-pt-8">
                  {episode.title}
                </Typography>
                <Typography variant="body-2" colorScheme="subtle" tag="p" className="v-pt-8" style={{ maxInlineSize: "62ch" }}>
                  Mina and Owen read only what is in the mail. They attribute it, and they do not weigh in.
                </Typography>
              </div>
              {episode.is_sample ? (
                <Flag messageType="information">
                  <FlagContent>
                    Sample edition from the included Northline mailbox. This recording uses Kokoro, the CPU fallback. With an NVIDIA GPU, the same script is spoken by Dia.
                  </FlagContent>
                </Flag>
              ) : null}
              {episode.status === "empty" ? (
                <Typography variant="body-2" colorScheme="subtle" tag="p">
                  {episode.error || "There was no mail in this window."}
                </Typography>
              ) : null}
              {episode.has_audio ? (
                <section className="hairline-card" aria-label="Player" style={{ padding: 20 }}>
                  <Utility vFlex vAlignItems="center" vGap={16}>
                    <Button
                      iconButton
                      buttonSize="large"
                      aria-label={playing ? "Pause" : "Play"}
                      onClick={() => {
                        const node = audioRef.current;
                        if (!node) return;
                        if (node.paused) void node.play();
                        else node.pause();
                      }}
                    >
                      {playing ? <Pause aria-hidden="true" size={24} /> : <Play aria-hidden="true" size={24} />}
                    </Button>
                    <div style={{ minInlineSize: 0, flex: 1 }}>
                      <input
                        className="brief-seek"
                        aria-label="Seek"
                        type="range"
                        min={0}
                        max={Math.max(episode.duration_ms / 1000, 0.1)}
                        step={0.1}
                        value={Math.min(time, episode.duration_ms / 1000)}
                        onChange={(event) => {
                          const next = Number(event.target.value);
                          if (audioRef.current) audioRef.current.currentTime = next;
                          setTime(next);
                        }}
                      />
                      <Utility vFlex vJustifyContent="between">
                        <Typography variant="label-small" colorScheme="subtle" tag="span">
                          {clock(time * 1000)}
                        </Typography>
                        <Typography variant="label-small" colorScheme="subtle" tag="span">
                          {clock(episode.duration_ms)}
                        </Typography>
                      </Utility>
                    </div>
                  </Utility>
                  <audio
                    ref={audioRef}
                    src={`/api/episodes/${episode.id}/audio`}
                    preload="metadata"
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                    onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
                    onEnded={() => setPlaying(false)}
                  />
                </section>
              ) : null}
              <section aria-label="Transcript">
                <Typography variant="headline-4" tag="h2">
                  Transcript
                </Typography>
                <ol className="brief-transcript">
                  {episode.segments?.map((segment, index) => {
                    const source = segment.source_ids.map((id) => mail[id]).filter(Boolean);
                    const on = index === active;
                    const delivery = deliveryLabel[segment.delivery] || segment.delivery;
                    return (
                      <li id={`segment-${index}`} key={segment.id} className="brief-segment" data-active={on ? "true" : "false"}>
                        <button
                          type="button"
                          className="brief-line"
                          onClick={() => {
                            const node = audioRef.current;
                            if (!node || !episode.has_audio) return;
                            node.currentTime = segment.start_ms / 1000;
                            void node.play();
                          }}
                        >
                          <Avatar aria-hidden="true">{segment.speaker_name.slice(0, 1)}</Avatar>
                          <span style={{ minInlineSize: 0 }}>
                            <span style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 8 }}>
                              <Typography variant="subtitle-3" tag="span">
                                {segment.speaker_name}
                              </Typography>
                              <Typography variant="label-small" colorScheme="subtle" tag="span">
                                {delivery}
                                {segment.nonverbal ? ` · ${segment.nonverbal}` : ""}
                                {on ? " · Playing" : ""}
                              </Typography>
                            </span>
                            <Typography variant="body-2" tag="span" style={{ display: "block", marginBlockStart: 4 }}>
                              {segment.text}
                            </Typography>
                          </span>
                        </button>
                        {source.length > 0 ? (
                          <div className="brief-sources">
                            {source.map((item) => (
                              <NovaLink key={item.id} element={<Link href={`/sources/${item.id}`} />}>
                                {item.from_name || item.from_addr} · {item.subject}
                              </NovaLink>
                            ))}
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              </section>
            </>
          )}
        </article>
        <aside className="brief-aside hairline-card" style={{ padding: 20 }}>
          <Typography variant="overline" tag="p">
            This edition
          </Typography>
          <dl className="meta-list">
            <div>
              <Typography variant="label" colorScheme="subtle" tag="dt">
                Hosts
              </Typography>
              <Typography variant="body-2" tag="dd">
                Mina, then Owen
              </Typography>
            </div>
            <div>
              <Typography variant="label" colorScheme="subtle" tag="dt">
                Voice
              </Typography>
              <Typography variant="body-2" tag="dd">
                {episode?.engine ? episode.engine : "Not rendered"}
              </Typography>
            </div>
            <div>
              <Typography variant="label" colorScheme="subtle" tag="dt">
                Script
              </Typography>
              <Typography variant="body-2" tag="dd">
                {episode?.script_model || "Not set"}
              </Typography>
            </div>
            <div>
              <Typography variant="label" colorScheme="subtle" tag="dt">
                Length
              </Typography>
              <Typography variant="body-2" tag="dd">
                {episode ? clock(episode.duration_ms) : "Not set"}
              </Typography>
            </div>
          </dl>
          {episode?.notes && episode.notes.length > 0 ? (
            <div className="stack-8" style={{ borderBlockStart: "1px solid var(--palette-default-border)", paddingBlockStart: 16 }}>
              <Typography variant="subtitle-3" tag="p">
                Guard
              </Typography>
              <ul className="stack-8" style={{ margin: 0, paddingInlineStart: 18 }}>
                {episode.notes.slice(0, 6).map((note) => (
                  <li key={note}>
                    <Typography variant="body-3" colorScheme="subtle" tag="span">
                      {note}
                    </Typography>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {episode ? (
            <div className="brief-actions">
              <Button disabled={!!busy} onClick={() => void generate("window")}>
                {busy && busy.includes("window") ? busy : "Generate now"}
              </Button>
              <Button colorScheme="secondary" disabled={!!busy} onClick={() => void generate("all")}>
                Use the whole mailbox
              </Button>
            </div>
          ) : null}
        </aside>
      </div>
      <Utility tag="footer" vFlex vJustifyContent="center" vPaddingVertical={24}>
        <Typography variant="label-small" colorScheme="subtle" tag="span">
          Mail, scripts and audio stay on this machine.
        </Typography>
      </Utility>
    </div>
  );
}

function Empty({ onGenerate, busy }: { onGenerate: (scope: "window" | "all") => void; busy: string | null }) {
  return (
    <div className="hairline-card" style={{ padding: 24 }}>
      <Typography variant="headline-1" tag="h1">
        Nothing to read yet
      </Typography>
      <Typography variant="body-2" colorScheme="subtle" tag="p" className="v-pt-12" style={{ maxInlineSize: "56ch" }}>
        Upload an .eml or .mbox file, or pull the last window from IMAP. The sample mailbox is already on disk if you generate from the whole library.
      </Typography>
      <Utility vFlex vFlexWrap vGap={8} className="v-pt-24">
        <Button disabled={!!busy} onClick={() => onGenerate("all")}>
          {busy || "Read the sample mailbox"} <ChevronRight aria-hidden="true" size={16} />
        </Button>
        <Button colorScheme="secondary" element={<Link href="/settings" />}>
          Upload mail
        </Button>
      </Utility>
    </div>
  );
}
