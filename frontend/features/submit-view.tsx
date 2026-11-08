"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Check,
  FileCode2,
  FlaskConical,
  LockKeyhole,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import { api, isMock } from "@/lib/api";
import { errorMessage, isAborted } from "@/lib/errors";
import { createJobSchema, type Health, type Profile, type Sample } from "@/lib/models";
import { readUpload } from "./read-upload";
import { ErrorNotice, Loading, SectionLabel } from "@/components/ui";

type SampleState = {
  data: Sample[];
  error?: string;
  loading: boolean;
  health?: Health;
  healthError?: string;
};
function sampleReducer(state: SampleState, action: Partial<SampleState>): SampleState {
  return { ...state, ...action };
}

export function SubmitView() {
  const router = useRouter();
  const [samples, dispatch] = useReducer(sampleReducer, { data: [], loading: true });
  const [reload, setReload] = useState(0);
  const [tab, setTab] = useState<"samples" | "paste" | "upload">("samples");
  const [selected, setSelected] = useState("evil-installer");
  const [profiles, setProfiles] = useState<Profile[]>(["dev-laptop", "ci"]);
  const [content, setContent] = useState("");
  const [filename, setFilename] = useState("install.sh");
  const [archive, setArchive] = useState<{ filename: string; content: string }>();
  const [tier, setTier] = useState<"standard" | "burn">("standard");
  const [claim, setClaim] = useState("");
  const [invite, setInvite] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const request = useRef<AbortController | null>(null);
  const submittingRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ loading: true, error: undefined });
    api
      .listSamples(controller.signal)
      .then((data) => dispatch({ data, loading: false }))
      .catch((reason: unknown) => {
        if (!isAborted(reason)) dispatch({ error: errorMessage(reason), loading: false });
      });
    api
      .getHealth(controller.signal)
      .then((health) => dispatch({ health, healthError: undefined }))
      .catch((reason: unknown) => {
        if (!isAborted(reason)) dispatch({ healthError: errorMessage(reason) });
      });
    return () => controller.abort();
  }, [reload]);
  useEffect(() => () => request.current?.abort(), []);

  function toggleProfile(profile: Profile) {
    setProfiles((current) =>
      current.includes(profile)
        ? current.filter((item) => item !== profile)
        : [...current, profile],
    );
  }

  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current) return;
    if (!profiles.length) {
      setError("Select at least one environment profile.");
      return;
    }
    const input = createJobSchema.safeParse({
      input_type: tab === "upload" ? "zip" : "paste",
      content: tab === "upload" ? archive?.content : content,
      filename: tab === "upload" ? archive?.filename : filename,
      claim: claim.trim() || undefined,
      profiles,
      tier,
      invite_code: invite || undefined,
    });
    if (tab !== "samples" && !input.success) {
      setError("Enter source text (up to 200,000 characters) and select a profile.");
      return;
    }
    if (tab === "samples" && !samples.data.some((sample) => sample.id === selected)) {
      setError("Select an available sample.");
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setError(undefined);
    request.current = new AbortController();
    try {
      const result =
        tab === "samples"
          ? await api.runSample(
              selected,
              { profiles, tier, invite_code: invite || undefined },
              request.current.signal,
            )
          : input.success
            ? await api.createJob(input.data, request.current.signal)
            : undefined;
      if (result) router.push(`/jobs/${encodeURIComponent(result.job_id)}`);
    } catch (reason: unknown) {
      if (!isAborted(reason)) setError(errorMessage(reason));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
      setInvite("");
    }
  }

  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">
            <span className="tiny-square" />
            UNTRUSTED CODE. OBSERVABLE BEHAVIOR.
          </p>
          <h1>
            Trust the evidence.
            <br />
            <span>Not the README.</span>
          </h1>
          <p className="hero-description">
            Inspect what code actually does in an isolated sandbox.
            <br className="desktop-break" /> Follow the signals. Trace every finding back
            to its source.
          </p>
        </div>
        <div className="hero-diagram" aria-label="Artifact to sandbox to evidence">
          <div className="diagram-node">
            <FileCode2 />
            <span>ARTIFACT</span>
          </div>
          <span className="diagram-connector" />
          <div className="diagram-node sandbox-node">
            <ShieldCheck />
            <span>AIRLOCK</span>
          </div>
          <span className="diagram-connector" />
          <div className="diagram-node">
            <Terminal />
            <span>EVIDENCE</span>
          </div>
          <span className="diagram-caption">
            {isMock ? "PREVIEW THE FLOW / SIMULATED" : "EXECUTION BELONGS TO THE BACKEND"}
          </span>
        </div>
      </section>
      <div className="workspace-grid">
        <form className="panel submit-panel" onSubmit={submit}>
          <div className="panel-heading">
            <SectionLabel number="01">Choose an artifact</SectionLabel>
            <span className="mono muted">START A NEW ANALYSIS</span>
          </div>
          <div
            className="input-tabs"
            role="tablist"
            aria-label="Artifact input"
            onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
              event.preventDefault();
              const tabs: ("samples" | "paste" | "upload")[] =
                samples.health?.capabilities?.zip && !isMock
                  ? ["samples", "paste", "upload"]
                  : ["samples", "paste"];
              const index = tabs.indexOf(tab);
              const next =
                event.key === "Home"
                  ? tabs[0]
                  : event.key === "End"
                    ? tabs[tabs.length - 1]
                    : tabs[
                        (index + (event.key === "ArrowLeft" ? -1 : 1) + tabs.length) %
                          tabs.length
                      ];
              setTab(next);
              event.currentTarget
                .querySelector<HTMLButtonElement>(`#${next}-tab`)
                ?.focus();
            }}
          >
            <button
              id="samples-tab"
              role="tab"
              type="button"
              aria-selected={tab === "samples"}
              tabIndex={tab === "samples" ? 0 : -1}
              aria-controls="samples-panel"
              onClick={() => setTab("samples")}
            >
              <FlaskConical size={16} />
              Team samples
            </button>
            <button
              id="paste-tab"
              role="tab"
              type="button"
              aria-selected={tab === "paste"}
              tabIndex={tab === "paste" ? 0 : -1}
              aria-controls="paste-panel"
              onClick={() => setTab("paste")}
            >
              <FileCode2 size={16} />
              Paste source
            </button>
            <button
              id="upload-tab"
              role="tab"
              type="button"
              aria-selected={tab === "upload"}
              aria-controls="upload-panel"
              tabIndex={tab === "upload" ? 0 : -1}
              disabled={isMock || !samples.health?.capabilities?.zip}
              onClick={() => setTab("upload")}
            >
              Upload file
            </button>
            <span
              className="unavailable-input"
              title="Requires backend capability confirmation"
            >
              npm registry unavailable
            </span>
          </div>
          {tab === "samples" ? (
            <div
              role="tabpanel"
              id="samples-panel"
              aria-labelledby="samples-tab"
              className="sample-list"
            >
              {samples.loading && <Loading>Loading samples…</Loading>}
              {samples.error && (
                <ErrorNotice
                  message={samples.error}
                  retry={() => setReload((value) => value + 1)}
                />
              )}
              {!samples.loading && !samples.error && !samples.data.length && (
                <p className="empty-state">No samples are available from this API.</p>
              )}
              {samples.data.map((sample, index) => (
                <label
                  className={`sample-card ${selected === sample.id ? "selected" : ""}`}
                  key={sample.id}
                >
                  <input
                    type="radio"
                    name="sample"
                    value={sample.id}
                    checked={selected === sample.id}
                    onChange={() => setSelected(sample.id)}
                  />
                  <span className="sample-index">0{index + 1}</span>
                  <span className="sample-copy">
                    <strong>{sample.title}</strong>
                    <span>{sample.description}</span>
                    <span className="sample-type">
                      {sample.input_type.toUpperCase()}
                      <span>TEAM-AUTHORED{isMock ? " · SYNTHETIC" : ""}</span>
                    </span>
                  </span>
                  <span className="radio-indicator">
                    {selected === sample.id && <Check size={13} />}
                  </span>
                </label>
              ))}
            </div>
          ) : tab === "upload" ? (
            <div
              role="tabpanel"
              id="upload-panel"
              aria-labelledby="upload-tab"
              className="paste-panel"
            >
              <label htmlFor="artifact-file">
                Python, shell, JavaScript, package.json or ZIP · up to 2 MiB
              </label>
              <input
                id="artifact-file"
                type="file"
                accept=".zip,.py,.sh,.bash,.js,.mjs,.cjs,.json"
                onChange={async (event) => {
                  setArchive(undefined);
                  const file = event.target.files?.[0];
                  if (!file) return;
                  try {
                    const upload = await readUpload(file);
                    if (upload.inputType === "zip") setArchive(upload);
                    else {
                      setFilename(upload.filename);
                      setContent(upload.content);
                      setTab("paste");
                    }
                    setError(undefined);
                  } catch (reason: unknown) {
                    setError(
                      reason instanceof Error
                        ? reason.message
                        : "Upload could not be read.",
                    );
                  }
                }}
              />
              <p className="fine-print">
                {archive
                  ? `Selected archive: ${archive.filename}`
                  : "ZIP requires one entrypoint: main.py, index.js, install.sh or package.json. Package hooks execute offline inside the sandbox."}
              </p>
              <label htmlFor="zip-claim">Claim (optional)</label>
              <input
                id="zip-claim"
                value={claim}
                maxLength={2000}
                onChange={(event) => setClaim(event.target.value)}
              />
              <label htmlFor="zip-invite">Invite code</label>
              <input
                id="zip-invite"
                type="password"
                autoComplete="off"
                value={invite}
                onChange={(event) => setInvite(event.target.value)}
              />
            </div>
          ) : (
            <div
              role="tabpanel"
              id="paste-panel"
              aria-labelledby="paste-tab"
              className="paste-panel"
            >
              <label htmlFor="source-filename">Original filename</label>
              <input
                id="source-filename"
                value={filename}
                maxLength={200}
                onChange={(event) => setFilename(event.target.value)}
                required
              />
              <label htmlFor="source-input">Source text</label>
              <textarea
                id="source-input"
                spellCheck={false}
                maxLength={200000}
                rows={10}
                value={content}
                onChange={(event) => setContent(event.target.value)}
                placeholder="Paste source for the backend to inspect…"
              />
              <label htmlFor="claim-input">
                What does it claim to do? <span className="muted">Optional</span>
              </label>
              <input
                id="claim-input"
                value={claim}
                maxLength={2000}
                onChange={(event) => setClaim(event.target.value)}
                placeholder="e.g. Formats CSV files offline"
              />
              <label htmlFor="invite-input">
                Invite code <span className="muted">If required by the backend</span>
              </label>
              <input
                id="invite-input"
                type="password"
                autoComplete="off"
                maxLength={200}
                value={invite}
                onChange={(event) => setInvite(event.target.value)}
              />
              {isMock && (
                <p className="availability-note">
                  Source submission is unavailable in simulation. Select a team sample, or
                  rebuild in live API mode.
                </p>
              )}
            </div>
          )}
          <div className="profile-section">
            <SectionLabel number="02">Select environment profiles</SectionLabel>
            <fieldset>
              <legend className="sr-only">Environment profiles</legend>
              {(["dev-laptop", "ci"] as const).map((profile) => (
                <label
                  key={profile}
                  className={`profile-option ${profiles.includes(profile) ? "checked" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={profiles.includes(profile)}
                    onChange={() => toggleProfile(profile)}
                  />
                  <span>
                    {profile === "dev-laptop" ? "Developer laptop" : "CI runner"}
                  </span>
                  <code>{profile}</code>
                </label>
              ))}
              <label className="profile-option disabled">
                <input type="checkbox" disabled />
                <span>Future date</span>
                <code>unavailable</code>
              </label>
            </fieldset>
            <label className="source-select">
              Isolation tier
              <select
                value={tier}
                onChange={(event) =>
                  setTier(event.target.value === "burn" ? "burn" : "standard")
                }
              >
                <option value="standard">Standard sandbox</option>
                <option
                  value="burn"
                  disabled={!samples.health?.capabilities?.burn || tab === "samples"}
                >
                  Burn VM (requires configured Vultr + invite)
                </option>
              </select>
            </label>
            {tier === "burn" && (
              <p className="availability-note">
                Creates a billed disposable VM. Completion requires confirmed deletion
                from Vultr. An invite code is required.
              </p>
            )}
            {samples.healthError && (
              <ErrorNotice
                message={samples.healthError}
                retry={() => setReload((value) => value + 1)}
              />
            )}
            {samples.health?.mode === "live" && !samples.health.observer_verified && (
              <p className="availability-note">
                Runner observation is not verified. Live analysis may be unavailable.
              </p>
            )}
            {samples.health?.mode === "mock" && !isMock && (
              <p className="simulation-notice">
                Backend MOCK/STUB mode: no real sandbox evidence.
              </p>
            )}
          </div>
          {error && <ErrorNotice message={error} />}
          <div className="submit-footer">
            <span>
              <LockKeyhole size={14} />
              {isMock
                ? "Simulation never executes code"
                : "Execution is delegated to the backend"}
            </span>
            <button
              className="primary-button"
              type="submit"
              disabled={
                submitting ||
                (tab !== "samples" && isMock) ||
                (tab === "upload" && !archive) ||
                (tab === "samples" && (samples.loading || !samples.data.length))
              }
            >
              {submitting
                ? "Submitting…"
                : isMock
                  ? "Run simulation"
                  : "Analyze artifact"}
              <ArrowRight size={17} />
            </button>
          </div>
        </form>
        <aside className="analysis-aside">
          <div className="panel aside-panel">
            <SectionLabel number="/">Evidence, not assurances</SectionLabel>
            <h2>
              A smaller blast radius.
              <br />A clearer picture.
            </h2>
            <ol className="explanation-list">
              <li>
                <span>01</span>
                <div>
                  <strong>Plan the inspection</strong>
                  <p>
                    Compare the stated purpose with behavior across selected environments.
                  </p>
                </div>
              </li>
              <li>
                <span>02</span>
                <div>
                  <strong>Observe the tripwires</strong>
                  <p>
                    File access, fake canary reads, network attempts, and resource limits.
                  </p>
                </div>
              </li>
              <li>
                <span>03</span>
                <div>
                  <strong>Follow the evidence</strong>
                  <p>
                    Findings link to events and source lines. Limitations stay visible.
                  </p>
                </div>
              </li>
            </ol>
            <div className="aside-note">
              <ShieldCheck size={19} />
              <p>
                No issue observed does not mean proven safe. A receipt records integrity,
                not a safety guarantee.
              </p>
            </div>
          </div>
          <div className="mode-note">
            <span className="mono">
              {isMock ? "DEVELOPMENT PREVIEW" : "LIVE API ADAPTER"}
            </span>
            <p>
              {isMock
                ? "These locally authored scenarios are synthetic. Host containment and Vultr services have not been verified here."
                : "Host provenance and containment are enforced by the backend and runner, not by this interface."}
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}
