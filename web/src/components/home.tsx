"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "next/navigation";
import { api, waitForJob } from "@/lib/api";
import type { Chain, DayGroup, Episode, Mail, OverviewStatus, Settings } from "@/lib/types";
import {
  Badge,
  Banner,
  BannerContent,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogHeader,
  Flag,
  FlagContent,
  Input,
  InputContainer,
  Label,
  Link as NovaLink,
  Radio,
  Select,
  Textarea,
  Typography,
} from "@/ui";

const VOICES = [
  { id: "kokoro_british", label: "Kokoro British" },
  { id: "kokoro_american", label: "Kokoro American" },
  { id: "dia", label: "Dia expressive" },
  { id: "my_voice", label: "My voice" },
];

export function Home() {
  const params = useSearchParams();
  const [mounted, setMounted] = useState(false);
  const [chains, setChains] = useState<Chain[] | null>(null);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(params.get("library") === "1" || Boolean(params.get("podcast")));
  const [today, setToday] = useState<Episode[]>([]);
  const [libraryDays, setLibraryDays] = useState<DayGroup[]>([]);
  const [libraryDay, setLibraryDay] = useState("");
  const [playing, setPlaying] = useState<Episode | null>(null);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, Mail>>({});
  const [targets, setTargets] = useState<Chain[]>([]);
  const [scope, setScope] = useState<"full" | "changed">("changed");
  const [question, setQuestion] = useState("");
  const [style, setStyle] = useState("quick");
  const [length, setLength] = useState("short");
  const [voice, setVoice] = useState("kokoro_british");
  const [making, setMaking] = useState(false);
  const [removed, setRemoved] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [inboxOpen, setInboxOpen] = useState(false);
  const [inboxQuery, setInboxQuery] = useState("");
  const [inboxChains, setInboxChains] = useState<Chain[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [overview, setOverview] = useState<OverviewStatus | null>(null);
  const [overviewDialog, setOverviewDialog] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const connected = params.get("connected");
    if (connected === "gmail") setNotice("Gmail is connected. Sync it from Settings when you want the latest mail.");
    if (connected === "outlook") setNotice("Outlook is connected. Sync it from Settings when you want the latest mail.");
  }, [params]);

  useEffect(() => {
    api<Settings>("/api/settings")
      .then((settings) => setVoice(settings.voice_preset || "kokoro_british"))
      .catch(() => undefined);
    refresh("");
    void loadIndex(params.get("podcast"));
    // The first load uses the URL once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const node = document.getElementById("podcast-dialog") as HTMLDialogElement | null;
    if (!node) return;
    const open = overviewDialog || targets.length > 0;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [targets, overviewDialog]);

  const overviewRefresh = overviewDialog && (overview?.new_count || 0) > 0;
  const showScope = overviewRefresh || (!overviewDialog && targets.some((item) => (item.new_count || 0) > 0));
  const chosenDay = libraryDays.find((day) => day.date === libraryDay) || libraryDays[0];

  async function refresh(nextQuery: string) {
    setError(null);
    try {
      const result = await api<{ chains: Chain[] }>(`/api/chains?q=${encodeURIComponent(nextQuery)}`);
      setChains(result.chains);
      setActiveQuery(nextQuery);
      setOverview(await api<OverviewStatus>("/api/overview"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The chains could not be loaded.");
      setChains([]);
    }
  }

  async function loadIndex(focusId: string | null) {
    const result = await api<{ podcasts: Episode[]; today: Episode[]; library: DayGroup[] }>("/api/podcasts");
    setToday(result.today || []);
    setLibraryDays(result.library || []);
    setLibraryDay((current) => {
      if (current && (result.library || []).some((day) => day.date === current)) return current;
      return result.library?.[0]?.date || "";
    });
    if (focusId) {
      const episode = await api<Episode>(`/api/episodes/${focusId}`);
      setPlaying(episode);
      setTranscript(episode.id);
      setLibraryOpen(true);
      await loadSources(episode);
    }
  }

  async function loadInbox(nextQuery: string) {
    const result = await api<{ chains: Chain[] }>(`/api/inbox?q=${encodeURIComponent(nextQuery)}`);
    setInboxChains(result.chains);
  }

  async function loadSources(episode: Episode) {
    const ids = new Set((episode.segments || []).flatMap((segment) => segment.source_ids));
    const entries = await Promise.all(
      [...ids].map(async (id) => {
        try {
          return [id, await api<Mail>(`/api/messages/${id}`)] as const;
        } catch {
          return null;
        }
      }),
    );
    setMessages((current) => {
      const next = { ...current };
      for (const entry of entries) {
        if (entry) next[entry[0]] = entry[1];
      }
      return next;
    });
  }

  function openChain(item: Chain) {
    setOverviewDialog(false);
    setTargets([item]);
    setScope((item.new_count || 0) > 0 ? "changed" : "full");
    setQuestion("");
    if (style === "full") {
      setStyle("quick");
      setLength("short");
    }
  }

  function openOverview() {
    setTargets([]);
    setOverviewDialog(true);
    setStyle("full");
    setLength("full");
    setQuestion("");
    setScope((overview?.new_count || 0) > 0 ? "changed" : "full");
  }

  async function makePodcast() {
    if (!overviewDialog && !targets.length) return;
    setMaking(true);
    setError(null);
    try {
      const started = await api<{ job_id: string }>("/api/podcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          overviewDialog
            ? {
                overview: true,
                question,
                style,
                length,
                voice_preset: voice,
                scope: overviewRefresh ? scope : "full",
              }
            : {
                chain_id: targets[0].id,
                chain_ids: targets.map((item) => item.id),
                question,
                style,
                length,
                voice_preset: voice,
                scope: showScope ? scope : "changed",
              },
        ),
      });
      const job = await waitForJob(started.job_id);
      if (job.status === "error" || !job.episode_id) throw new Error(job.error || "The podcast could not be made.");
      const episode = await api<Episode>(`/api/episodes/${job.episode_id}`);
      setTargets([]);
      setOverviewDialog(false);
      setQuestion("");
      setPlaying(episode);
      setTranscript(episode.id);
      await loadSources(episode);
      await loadIndex(null);
      await refresh(activeQuery);
      setPlaying(episode);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The podcast could not be made.");
    } finally {
      setMaking(false);
    }
  }

  async function remove(id: string) {
    setRemoved(id);
    setToday((current) => current.filter((item) => item.id !== id));
    setLibraryDays((current) =>
      current
        .map((day) => {
          const podcasts = day.podcasts.filter((item) => item.id !== id);
          return { ...day, podcasts, count: podcasts.length };
        })
        .filter((day) => day.count > 0),
    );
    if (playing?.id === id) setPlaying(null);
    await api(`/api/podcasts/${id}`, { method: "DELETE" });
  }

  async function undo() {
    if (!removed) return;
    const id = removed;
    setRemoved(null);
    await api(`/api/podcasts/${id}/restore`, { method: "POST" });
    await loadIndex(id);
  }

  async function openPodcast(item: Episode) {
    const full = item.segments ? item : await api<Episode>(`/api/episodes/${item.id}`);
    setPlaying(full);
    setTranscript(full.id);
    await loadSources(full);
  }

  return (
    <div className="page-frame fade-up reading-column stack-24">
      <article className="hairline-card chain-card" aria-labelledby="overview-title">
        <Typography variant="overline" tag="p">
          Daily inbox
        </Typography>
        <Typography id="overview-title" variant="headline-2" tag="h2" className="v-pt-8">
          Full inbox overview
        </Typography>
        <Typography variant="body-2" tag="p" className="v-pt-8">
          {overview
            ? `${overview.email_count} ${overview.email_count === 1 ? "email" : "emails"} ${overview.period_label}, in ${overview.chain_count} ${overview.chain_count === 1 ? "chain" : "chains"}. Each email is read in full, most significant first. Notifications, spam, and no-reply mail stay out.`
            : "Loading the inbox…"}
        </Typography>
        {overview?.generated ? (
          <div className="v-pt-8">
            <Badge badgeType="stable">Generated today</Badge>
          </div>
        ) : null}
        {overview && overview.new_count > 0 ? (
          <Typography variant="body-2" tag="p" className="v-pt-8">
            {overview.new_count} new {overview.new_count === 1 ? "email" : "emails"} since this overview.
          </Typography>
        ) : null}
        <div className="ask-row v-pt-16">
          {overview && overview.new_count > 0 ? (
            <Button className="touch-44" disabled={making} onClick={openOverview}>
              Refresh overview
            </Button>
          ) : overview?.generated && overview.episode_id ? (
            <Button
              className="touch-44"
              colorScheme="secondary"
              onClick={() => {
                const episode = today.find((item) => item.id === overview.episode_id);
                if (episode) void openPodcast(episode);
              }}
            >
              Play overview
            </Button>
          ) : (
            <Button className="touch-44" disabled={making || overview?.email_count === 0} onClick={openOverview}>
              Full inbox overview
            </Button>
          )}
        </div>
      </article>
      <div>
        <Typography variant="overline" tag="p">
          PodcastBox
        </Typography>
        <Typography variant="headline-1" tag="h1" className="v-pt-8">
          Chains worth hearing
        </Typography>
        <Typography variant="body-2" colorScheme="subtle" tag="p" className="v-pt-12">
          Each topic is shown once. Turn one chain into a two-host podcast.
        </Typography>
      </div>
      {notice ? (
        <Flag messageType="success">
          <FlagContent>{notice}</FlagContent>
        </Flag>
      ) : null}
      {error ? (
        <Banner messageType="error">
          <BannerContent>{error}</BannerContent>
        </Banner>
      ) : null}
      <form
        className="ask-row"
        onSubmit={(event) => {
          event.preventDefault();
          void refresh(query);
        }}
      >
        <Label htmlFor="ask" className="v-sr">
          Ask about your mail
        </Label>
        <InputContainer>
          <Input
            id="ask"
            value={query}
            placeholder='Try "update on Atlas" or "my communications with Priya"'
            onChange={(event) => setQuery(event.target.value)}
          />
        </InputContainer>
        <Button type="submit" colorScheme="secondary" className="touch-44">
          Find
        </Button>
        <Button type="button" colorScheme="tertiary" className="touch-44" onClick={() => setLibraryOpen(true)}>
          Library
        </Button>
      </form>

      <section className="stack-16" aria-label="Today's podcasts">
        <div>
          <Typography variant="headline-3" tag="h2">
            Today&apos;s podcasts
          </Typography>
          <Typography variant="body-3" colorScheme="subtle" tag="p" className="v-pt-8">
            Generated today. They move to the Library at midnight.
          </Typography>
        </div>
        {today.length === 0 ? (
          <Typography variant="body-2" colorScheme="subtle" tag="p">
            Nothing generated today yet.
          </Typography>
        ) : (
          <div className="today-list">
            {today.map((item) => (
              <article key={item.id} className="hairline-card chain-card">
                <Typography variant="headline-4" tag="h3">
                  {item.title}
                </Typography>
                <div className="ask-row v-pt-12">
                  <Button className="touch-44" colorScheme="secondary" onClick={() => void openPodcast(item)}>
                    Play
                  </Button>
                  <Button colorScheme="tertiary" className="touch-44" onClick={() => void openPodcast(item)}>
                    Transcript
                  </Button>
                  <Button colorScheme="tertiary" destructive className="touch-44" onClick={() => void remove(item.id)}>
                    Delete
                  </Button>
                </div>
                {playing?.id === item.id ? <Player episode={playing} messages={messages} open={transcript === item.id} /> : null}
              </article>
            ))}
          </div>
        )}
        {removed && !libraryOpen ? (
          <Flag messageType="success">
            <FlagContent>
              Deleted.{" "}
              <Button colorScheme="tertiary" onClick={() => void undo()}>
                Undo
              </Button>
            </FlagContent>
          </Flag>
        ) : null}
      </section>

      {chains === null ? (
        <Typography variant="body-2" tag="p" role="status">
          Loading chains…
        </Typography>
      ) : chains.length === 0 ? (
        <div className="hairline-card" style={{ padding: 24 }}>
          <Typography variant="headline-4" tag="h2">
            {activeQuery ? "No matching chain" : "Nothing to brief yet"}
          </Typography>
          <Typography variant="body-2" colorScheme="subtle" tag="p" className="v-pt-8">
            {activeQuery
              ? "Try a project name or a person. Low-value mail such as receipts and reminders is left out."
              : "Connect Gmail or Outlook in Settings, or widen the review period. Reminders, receipts, and newsletters stay out."}
          </Typography>
        </div>
      ) : (
        <div className="chain-list">
          {chains.map((item) => (
            <article key={item.id} className="hairline-card chain-card">
              <Typography variant="headline-4" tag="h2">
                {item.title}
              </Typography>
              {item.new_label ? (
                <div className="v-pt-8">
                  <Badge badgeType="stable">{item.new_label}</Badge>
                </div>
              ) : null}
              <Typography variant="body-2" tag="p" className="v-pt-8">
                {item.reason}
              </Typography>
              <Typography variant="body-3" colorScheme="subtle" tag="p" className="v-pt-8">
                {names(item)} · {range(item.date_start, item.date_end)}
              </Typography>
              <div className="v-pt-16">
                <Button className="touch-44" disabled={making} onClick={() => openChain(item)}>
                  Turn into podcast
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}

      <Dialog
        id="podcast-dialog"
        className="podcast-dialog"
        aria-labelledby="podcast-title"
        onClose={() => {
          setTargets([]);
          setOverviewDialog(false);
        }}
      >
        <DialogHeader id="podcast-title">{overviewDialog ? "Full inbox overview" : dialogTitle(targets)}</DialogHeader>
        <DialogContent>
          <div className="stack-16">
            {targets.length > 1 ? (
              <Typography variant="body-2" tag="p">
                {targets.map((item) => item.title).join(", ")}
              </Typography>
            ) : null}
            {showScope ? (
              <div role="radiogroup" aria-label={overviewDialog ? "How much of the inbox to read" : "How much of the chain to read"}>
                <Typography variant="body-2" tag="p">
                  What should Mina and Owen read?
                </Typography>
                <div className="scope-choice v-pt-8">
                  <Radio id="scope-changed" name="podcast-scope" checked={scope === "changed"} onChange={() => setScope("changed")} />
                  <Label htmlFor="scope-changed">{overviewDialog ? "Only what's new" : "Only what's changed"}</Label>
                </div>
                <div className="scope-choice">
                  <Radio id="scope-full" name="podcast-scope" checked={scope === "full"} onChange={() => setScope("full")} />
                  <Label htmlFor="scope-full">{overviewDialog ? "Full" : "Full chain"}</Label>
                </div>
              </div>
            ) : (
              <Typography variant="body-2" tag="p">
                What do you want to know?
              </Typography>
            )}
            <Textarea
              id="question"
              aria-label="What do you want to know?"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="What changed on the ship date?"
            />
            <Label htmlFor="style">How should it be communicated?</Label>
            <Select id="style" value={style} onChange={(event) => setStyle(event.target.value)}>
              {overviewDialog ? <option value="full">Full</option> : null}
              <option value="quick">Quick brief</option>
              <option value="deep">Deep dive</option>
              <option value="action">Action focused</option>
            </Select>
            {overviewDialog && style === "full" ? (
              <Typography variant="body-3" colorScheme="subtle" tag="p">
                Length follows the inbox. Every email is read in full.
              </Typography>
            ) : (
              <>
                <Label htmlFor="length">Length</Label>
                <Select id="length" value={length === "full" ? "short" : length} onChange={(event) => setLength(event.target.value)}>
                  <option value="short">Short</option>
                  <option value="medium">Medium</option>
                  <option value="long">Long</option>
                </Select>
              </>
            )}
            <Label htmlFor="voice">Voice</Label>
            <Select id="voice" value={voice} onChange={(event) => setVoice(event.target.value)}>
              {VOICES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
            <div className="ask-row">
              <Button className="touch-44" disabled={(!overviewDialog && !targets.length) || making} onClick={() => void makePodcast()}>
                {making ? "Making the podcast…" : "Make the podcast"}
              </Button>
              <Button
                type="button"
                colorScheme="tertiary"
                className="touch-44"
                onClick={() => {
                  setTargets([]);
                  setOverviewDialog(false);
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {libraryOpen
        ? createPortal(
            <div className="library-root">
              <button type="button" className="library-backdrop" aria-label="Close library" onClick={() => setLibraryOpen(false)} />
              <aside className="library-drawer" aria-label="Library">
                <div className="ask-row">
                  <Typography variant="headline-3" tag="h2">
                    Library
                  </Typography>
                  <Button colorScheme="tertiary" className="touch-44" onClick={() => setLibraryOpen(false)}>
                    Close
                  </Button>
                </div>
                {removed ? (
                  <Flag messageType="success">
                    <FlagContent>
                      Deleted.{" "}
                      <Button colorScheme="tertiary" onClick={() => void undo()}>
                        Undo
                      </Button>
                    </FlagContent>
                  </Flag>
                ) : null}
                {libraryDays.length === 0 ? (
                  <Typography variant="body-2" colorScheme="subtle" tag="p" className="v-pt-16">
                    Podcasts move here after the day they were generated.
                  </Typography>
                ) : (
                  <>
                    <div className="v-pt-16">
                      <Label htmlFor="library-day">Day</Label>
                      <Select
                        id="library-day"
                        aria-label="Library day"
                        value={chosenDay?.date || ""}
                        onChange={(event) => setLibraryDay(event.target.value)}
                      >
                        {libraryDays.map((day) => (
                          <option key={day.date} value={day.date}>
                            {day.label} ({day.count})
                          </option>
                        ))}
                      </Select>
                    </div>
                    <ul className="library-list">
                      {(chosenDay?.podcasts || []).map((item) => (
                        <li key={item.id}>
                          <button type="button" className="library-item" onClick={() => void openPodcast(item)}>
                            <Typography variant="subtitle-2" tag="span">
                              {item.title}
                            </Typography>
                            <Typography variant="body-3" colorScheme="subtle" tag="span">
                              {item.brief_date}
                              {item.question ? ` · ${item.question}` : ""}
                            </Typography>
                          </button>
                          <Button colorScheme="tertiary" destructive onClick={() => void remove(item.id)}>
                            Delete
                          </Button>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {playing && libraryOpen ? <Player episode={playing} messages={messages} open /> : null}
              </aside>
            </div>,
            document.body,
          )
        : null}

      {mounted
        ? createPortal(
            <div className="all-mail">
              {inboxOpen ? (
                <div className="all-mail-panel" role="dialog" aria-label="All emails">
                  <Typography variant="headline-4" tag="h2">
                    All emails
                  </Typography>
                  <Typography variant="body-3" colorScheme="subtle" tag="p" className="v-pt-8">
                    Every chain in this review period, including ones that were not suggested. Notifications and automated mail stay out.
                  </Typography>
                  <form
                    className="ask-row v-pt-12"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void loadInbox(inboxQuery);
                    }}
                  >
                    <Label htmlFor="inbox-search" className="v-sr">
                      Search all emails
                    </Label>
                    <InputContainer>
                      <Input
                        id="inbox-search"
                        value={inboxQuery}
                        placeholder="Search by person or subject"
                        onChange={(event) => {
                          setInboxQuery(event.target.value);
                          void loadInbox(event.target.value);
                        }}
                      />
                    </InputContainer>
                  </form>
                  {inboxChains === null ? (
                    <Typography variant="body-2" tag="p" className="v-pt-12" role="status">
                      Loading mail…
                    </Typography>
                  ) : inboxChains.length === 0 ? (
                    <Typography variant="body-2" tag="p" className="v-pt-12">
                      Nothing in this review period matches.
                    </Typography>
                  ) : (
                    <ul className="inbox-list">
                      {inboxChains.map((item) => (
                        <li key={item.id}>
                          <label className="inbox-row" htmlFor={`mail-${item.id}`}>
                            <Checkbox
                              id={`mail-${item.id}`}
                              checked={picked.includes(item.id)}
                              onChange={() =>
                                setPicked((current) =>
                                  current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id],
                                )
                              }
                            />
                            <span>
                              <Typography variant="subtitle-3" tag="span">
                                {item.title}
                              </Typography>
                              <Typography variant="body-3" colorScheme="subtle" tag="span">
                                {item.reason}
                                {item.new_label ? ` · ${item.new_label}` : ""}
                              </Typography>
                            </span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="ask-row v-pt-12">
                    <Button
                      className="touch-44"
                      disabled={!picked.length}
                      onClick={() => {
                        const chosen = (inboxChains || []).filter((item) => picked.includes(item.id));
                        if (!chosen.length) return;
                        setTargets(chosen);
                        setScope(chosen.some((item) => (item.new_count || 0) > 0) ? "changed" : "full");
                        setInboxOpen(false);
                      }}
                    >
                      Turn into podcast
                    </Button>
                    <Button type="button" colorScheme="tertiary" className="touch-44" onClick={() => setInboxOpen(false)}>
                      Close
                    </Button>
                  </div>
                </div>
              ) : null}
              <Button
                className="touch-44"
                colorScheme="secondary"
                aria-expanded={inboxOpen}
                onClick={() => {
                  const next = !inboxOpen;
                  setInboxOpen(next);
                  if (next) void loadInbox(inboxQuery);
                }}
              >
                All emails
              </Button>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function Player({ episode, messages, open }: { episode: Episode; messages: Record<string, Mail>; open: boolean }) {
  if (!open) return null;
  return (
    <div className="v-pt-16 stack-16">
      {episode.has_audio ? <audio controls src={`/api/episodes/${episode.id}/audio`} style={{ inlineSize: "100%" }} /> : null}
      {(episode.segments || []).map((segment) => (
        <div key={segment.id}>
          <Typography variant="subtitle-3" tag="p">
            {segment.speaker_name}
          </Typography>
          <Typography variant="body-2" tag="p">
            {segment.text}
          </Typography>
          <Typography variant="body-3" colorScheme="subtle" tag="p">
            {segment.source_ids.map((id, index) => {
              const mail = messages[id];
              const who = mail?.from_name || "A saved email";
              const subject = mail?.subject || "Source email";
              return (
                <span key={id}>
                  {index ? " " : ""}
                  {who}
                  {": "}
                  <NovaLink href={`/api/messages/${id}`} noUnderline>
                    {subject}
                  </NovaLink>
                </span>
              );
            })}
          </Typography>
        </div>
      ))}
    </div>
  );
}

function dialogTitle(targets: Chain[]) {
  if (targets.length === 1) return targets[0].title;
  if (targets.length > 1) return "Selected chains";
  return "Podcast";
}

function names(chain: Chain) {
  const list = chain.participants.map((person) => person.name).filter(Boolean);
  if (list.length <= 4) return list.join(", ");
  return `${list.slice(0, 3).join(", ")}, and ${list.length - 3} more`;
}

function range(start: string, end: string) {
  const left = label(start);
  const right = label(end);
  if (!left) return "";
  if (!right || left === right) return left;
  return `${left} to ${right}`;
}

function label(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(date);
}
