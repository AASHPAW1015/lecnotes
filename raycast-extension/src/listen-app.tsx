import {
  Action,
  ActionPanel,
  Color,
  Icon,
  List,
  Toast,
  closeMainWindow,
  getPreferenceValues,
  showHUD,
  showToast,
} from "@raycast/api";
import { usePromise } from "@raycast/utils";
import { execFile, spawn } from "node:child_process";
import { existsSync, openSync, readFileSync, statSync, unlinkSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { useEffect } from "react";

const run = promisify(execFile);

// `lecnote stop` transcribes and writes notes for a minute or more, so it runs
// detached with its output here; a failure is then shown the next time the
// list opens instead of vanishing.
const STOP_LOG = join(homedir(), ".lecnote", "raycast-stop.log");

type AudioApp = { name: string; playing: boolean; bundle: string; path: string };
type Status = {
  recording: null | { mode: string; source: string; foreground: boolean; elapsed: number };
  processing: { stage: string; mode: string; elapsed: number }[];
};
type Mode = "notion" | "png" | "excalidraw";

function lecnote(): string {
  const { lecnotePath } = getPreferenceValues<{ lecnotePath: string }>();
  return lecnotePath.trim().replace(/^~(?=\/)/, homedir());
}

async function lecnoteJSON<T>(...args: string[]): Promise<T> {
  // The first call builds the capture helper, which takes a few seconds.
  const { stdout } = await run(lecnote(), args, { timeout: 120_000 });
  return JSON.parse(stdout) as T;
}

function errorText(error: unknown): string {
  const e = error as { stderr?: string; message?: string };
  const lines = (e.stderr || e.message || String(error)).trim().split("\n");
  return lines.find((l) => l.startsWith("error:"))?.slice(6).trim() || lines[0];
}

function elapsed(seconds: number): string {
  const s = Math.floor(seconds);
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

function sourceLabel(source: string): string {
  if (source.startsWith("app:")) return source.slice(4);
  return source === "system" ? "system audio" : "microphone";
}

function bundleOf(path: string): string | undefined {
  const i = path.indexOf(".app/");
  return i === -1 ? undefined : path.slice(0, i + 4);
}

function lastFailure(): string | undefined {
  if (!existsSync(STOP_LOG)) return undefined;
  // Old failures are not news; only show one from the last few hours.
  if (Date.now() - statSync(STOP_LOG).mtimeMs > 6 * 3600_000) return undefined;
  const lines = readFileSync(STOP_LOG, "utf8").trim().split("\n");
  const error = lines.find((l) => l.startsWith("error:"));
  return error ? error.slice(6).trim() : undefined;
}

async function startRecording(app: AudioApp, mode: Mode) {
  const toast = await showToast({ style: Toast.Style.Animated, title: `Starting ${app.name}…` });
  try {
    await run(lecnote(), ["start", "--app", app.name, mode], { timeout: 120_000 });
    if (existsSync(STOP_LOG)) unlinkSync(STOP_LOG); // a new run supersedes the old failure
    await closeMainWindow();
    await showHUD(`● Recording ${app.name} only${mode === "notion" ? "" : ` → ${mode}`}`);
  } catch (error) {
    toast.style = Toast.Style.Failure;
    toast.title = `Could not start ${app.name}`;
    toast.message = errorText(error);
  }
}

async function stopRecording() {
  const out = openSync(STOP_LOG, "w");
  const child = spawn(lecnote(), ["stop"], { detached: true, stdio: ["ignore", out, out] });
  child.unref();
  await closeMainWindow();
  await showHUD("■ Stopped — notes land on your clipboard when ready");
}

export default function Command() {
  const { data, isLoading, revalidate, error } = usePromise(async () => {
    const [status, apps] = await Promise.all([
      lecnoteJSON<Status>("status", "--json"),
      lecnoteJSON<AudioApp[]>("apps", "--json"),
    ]);
    return { status, apps, failure: lastFailure() };
  });

  // Keep elapsed times and processing stages moving while the list is open.
  const busy = !!data && (!!data.status.recording || data.status.processing.length > 0);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(revalidate, 2000);
    return () => clearInterval(timer);
  }, [busy]);

  const refresh = (
    <Action title="Refresh" icon={Icon.ArrowClockwise} shortcut={{ modifiers: ["cmd"], key: "r" }} onAction={revalidate} />
  );

  if (error) {
    return (
      <List>
        <List.EmptyView
          icon={Icon.Warning}
          title="Could not run lecnote"
          description={`${errorText(error)}\n\nCheck the lecnote command path in this extension's preferences.`}
          actions={<ActionPanel>{refresh}</ActionPanel>}
        />
      </List>
    );
  }

  const recording = data?.status.recording;
  const playing = data?.apps.filter((a) => a.playing) ?? [];
  const idle = data?.apps.filter((a) => !a.playing) ?? [];

  const appItem = (app: AudioApp) => {
    const bundle = bundleOf(app.path);
    return (
      <List.Item
        key={app.name}
        title={app.name}
        icon={bundle ? { fileIcon: bundle } : Icon.SpeakerOn}
        accessories={app.playing ? [{ tag: { value: "playing", color: Color.Green } }] : []}
        actions={
          <ActionPanel>
            <Action title="Record → Notion Notes" icon={Icon.Microphone} onAction={() => startRecording(app, "notion")} />
            <Action title="Record → PNG Diagrams" icon={Icon.Image} onAction={() => startRecording(app, "png")} />
            <Action title="Record → Excalidraw" icon={Icon.Pencil} onAction={() => startRecording(app, "excalidraw")} />
            {refresh}
          </ActionPanel>
        }
      />
    );
  };

  return (
    <List isLoading={isLoading} searchBarPlaceholder="Pick the app playing your lecture…">
      {recording && (
        <List.Section title="Now">
          <List.Item
            title={`Recording ${sourceLabel(recording.source)}`}
            subtitle={elapsed(recording.elapsed)}
            icon={{ source: Icon.CircleFilled, tintColor: Color.Red }}
            accessories={[{ text: recording.mode }]}
            actions={
              <ActionPanel>
                <Action title="Stop and Make Notes" icon={Icon.Stop} onAction={stopRecording} />
                {refresh}
              </ActionPanel>
            }
          />
        </List.Section>
      )}

      {data && data.status.processing.length > 0 && (
        <List.Section title="Processing">
          {data.status.processing.map((job, i) => (
            <List.Item
              key={i}
              title={job.stage}
              subtitle={elapsed(job.elapsed)}
              icon={{ source: Icon.Hourglass, tintColor: Color.Orange }}
              accessories={[{ text: job.mode }]}
              actions={<ActionPanel>{refresh}</ActionPanel>}
            />
          ))}
        </List.Section>
      )}

      {data?.failure && !busy && (
        <List.Section title="Last run">
          <List.Item
            title="Failed"
            subtitle={data.failure}
            icon={{ source: Icon.Warning, tintColor: Color.Red }}
            actions={
              <ActionPanel>
                <Action.Open title="Open Full Log" target={STOP_LOG} />
                <Action
                  title="Dismiss"
                  icon={Icon.XMarkCircle}
                  onAction={() => {
                    unlinkSync(STOP_LOG);
                    revalidate();
                  }}
                />
              </ActionPanel>
            }
          />
        </List.Section>
      )}

      {/* One recorder at a time: while recording, the only useful action is Stop. */}
      {!recording && (
        <>
          <List.Section title="Playing now">{playing.map(appItem)}</List.Section>
          <List.Section title="Other apps with audio">{idle.map(appItem)}</List.Section>
          {!isLoading && data && data.apps.length === 0 && (
            <List.EmptyView
              icon={Icon.SpeakerOff}
              title="No app is using audio"
              description="Start the lecture playing, then press ⌘R."
              actions={<ActionPanel>{refresh}</ActionPanel>}
            />
          )}
        </>
      )}
    </List>
  );
}
