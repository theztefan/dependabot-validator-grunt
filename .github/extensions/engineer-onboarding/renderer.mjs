const topics = [
    ["overview", "Start here"],
    ["run", "Run it"],
    ["flows", "Full flows"],
    ["architecture", "Architecture"],
    ["customize", "Customize"],
    ["safety", "Safety model"],
    ["change", "Make changes"],
];

export const topicSummaries = {
    overview: {
        purpose:
            "Review one Dependabot dismissal request or triage one alert using deterministic npm evidence plus bounded Copilot investigation.",
        remember: [
            "The CLI is read-only and publishes local report.json and report.md files only.",
            "Deterministic Python owns every final decision.",
            "Agent output is untrusted evidence, never authority.",
        ],
        files: ["README.md", "docs/README.md", "docs/architecture.md"],
    },
    run: {
        commands: [
            "uv sync --all-groups --locked",
            "uv run python -m copilot download-runtime",
            "uv run dependabot-validator-grunt review-dismissal --offline-fixture examples/offline-cases/not-used-absent",
            "uv run dependabot-validator-grunt triage-alert --offline-fixture examples/offline-cases/triage-vulnerable",
        ],
        credentials: ["DEPENDABOT_GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"],
        remember: ["Offline fixtures are the default credential-free development path."],
    },
    flows: {
        useCases: [
            "Offline dismissal review",
            "Live GHEC dismissal review",
            "Offline alert triage",
            "Live GHEC alert triage",
        ],
        sharedInvariant:
            "Every successful path ends with deterministic validation and atomic local report publication.",
        driftBehavior:
            "Dismissal drift becomes a stale lifecycle result; triage alert drift fails validation.",
    },
    architecture: {
        flow: [
            "CLI input",
            "typed evidence collection",
            "deterministic policy engine",
            "optional bounded Copilot investigation",
            "optional no-tool judge review",
            "deterministic reconciliation",
            "local report publication",
        ],
        coreModules: [
            "main.py",
            "workflow.py",
            "models.py",
            "github.py",
            "npm.py",
            "dependency_graph.py",
            "yarn.py",
            "pnpm.py",
            "policy.py",
            "deterministic.py",
            "agentic.py",
            "reachability.py",
            "copilot.py",
            "judge.py",
            "copilot_assets.py",
            "copilot_tools.py",
            "reporting.py",
        ],
    },
    customize: {
        ownership: {
            policy: "src/dependabot_validator_grunt/policies/default.json",
            engine: "src/dependabot_validator_grunt/deterministic.py",
            agent: "src/dependabot_validator_grunt/agents/dependency-risk-investigator/",
            judgeAgent: "src/dependabot_validator_grunt/agents/dependency-risk-judge/",
            sessionSafety:
                "src/dependabot_validator_grunt/system-prompts/",
            methodology:
                "src/dependabot_validator_grunt/skills/",
            boundedToolsAndFindingValidation: "src/dependabot_validator_grunt/agentic.py",
            sdkToolSchemas:
                "src/dependabot_validator_grunt/tools/repository-tools.json and src/dependabot_validator_grunt/copilot_tools.py",
        },
        remember: ["Change the smallest file that owns the behavior."],
    },
    safety: {
        controls: [
            "CopilotClient(mode=\"empty\")",
            "exact tool allowlist: list_files, read_file, search, analyze_reachability",
            "deny-by-default permission handler",
            "separate GitHub and Copilot credential roles and constructor paths",
            "exact custom-agent and custom-skill load-event validation",
            "schema validation and deterministic reconciliation before publication",
        ],
    },
    change: {
        sequence: [
            "Use the docs and ADR indexes to select only change-relevant context.",
            "Update the workflow contract before changing behavior or safety.",
            "Resume any active .logs plan; never publish raw research or phase history.",
            "Run the narrowest relevant baseline.",
            "Make a focused change with offline tests.",
            "Request an independent review.",
            "Run the full baseline.",
        ],
        fullBaseline: [
            "uv run pytest",
            "uv run ruff check .",
            "uv run ruff format --check .",
            "uv run pyright",
            "uv build",
        ],
    },
};

const applicationFlows = [
    {
        id: "offline-dismissal",
        title: "Offline dismissal review",
        subtitle: "Credential-free scripted evaluation, with explicit real-model selection when needed.",
        command:
            "uv run dependabot-validator-grunt review-dismissal --offline-fixture <case-directory>",
        labels: ["offline_fixture", "dismissal", "request + alert"],
        stages: [
            {
                title: "Validate CLI configuration",
                owner: "main.py",
                detail:
                    "Reject live inputs mixed with --offline-fixture. --model explicitly selects real Copilot and requires its credential.",
            },
            {
                title: "Load the fixture and policy",
                owner: "workflow.py · policy.py",
                detail:
                    "Validate request.json, alert.json, repository files, and policy precedence: CLI file, fixture policy.json, then packaged default.",
            },
            {
                title: "Build typed npm evidence",
                owner: "npm.py · models.py",
                detail:
                    "Inspect package-lock v2/v3, Yarn Classic v1, pnpm v9.0, or partial manifest-only evidence without executing repository code; create the canonical EvidenceBundle and write input/evidence artifacts.",
            },
            {
                title: "Check request lifecycle",
                owner: "workflow.py",
                detail: "A non-pending or expired request stops recommendation processing.",
                branches: [
                    {
                        label: "Terminal lifecycle",
                        result:
                            "Publish not_pending or expired directly; skip deterministic analysis, agent analysis, drift re-check, and route validation.",
                        tone: "safe",
                    },
                    {
                        label: "Pending",
                        result: "Continue into deterministic dismissal routing.",
                    },
                ],
            },
            {
                title: "Run deterministic dismissal rules",
                owner: "deterministic.py",
                detail:
                    "Apply policy routes and closed npm proofs. The result is either a final DismissalDecision or a typed AgentTask.",
                branches: [
                    {
                        label: "Final decision",
                        result: "Use approve, deny, or human_review and continue to drift validation.",
                        tone: "safe",
                    },
                    {
                        label: "AgentTask",
                        result: "Use agent-response.json by default, or real Copilot when --model selects it.",
                        tone: "agent",
                    },
                    {
                        label: "AgentTask without a boundary",
                        result: "Fail configuration with exit 2 before agent execution or report publication.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Validate investigator evidence",
                owner: "copilot.py · agentic.py",
                detail:
                    "When an AgentTask exists, preserve raw output and validate identities, permissions, schema, and citations.",
                optional: true,
                branches: [
                    {
                        label: "Valid finding",
                        result: "Continue to optional judge review.",
                        tone: "agent",
                    },
                    {
                        label: "Invalid finding",
                        result: "Retry within the shared budget or stop with an explicit Copilot failure.",
                        tone: "warning",
                    },
                    {
                        label: "SDK failure, timeout, or malformed output",
                        result: "Preserve failure/raw artifacts and stop with exit 6.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Challenge a real-model finding",
                owner: "judge.py",
                detail:
                    "Real Copilot findings receive one no-tool review with evidence and applicability critics. Scripted fixture turns skip this stage.",
                optional: true,
                branches: [
                    {
                        label: "Accept or valid replacement",
                        result: "Pass the selected validated finding to deterministic reconciliation.",
                        tone: "agent",
                    },
                    {
                        label: "Judge failure",
                        result: "Record judge-review.json and retain the valid primary finding.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Reconcile the selected finding",
                owner: "deterministic.py",
                detail:
                    "After optional judge review, independently prove permitted outcomes and fail closed when approval evidence is insufficient.",
                optional: true,
            },
            {
                title: "Re-read fixture state for pending requests",
                owner: "workflow.py",
                detail:
                    "Use post-analysis-request.json and post-analysis-alert.json when present; otherwise re-read the original fixture snapshots.",
                optional: true,
                branches: [
                    {
                        label: "Request or alert changed",
                        result: "Replace the recommendation with a stale lifecycle result.",
                        tone: "warning",
                    },
                    {
                        label: "Unchanged",
                        result: "Keep the deterministic or reconciled decision.",
                        tone: "safe",
                    },
                ],
            },
            {
                title: "Validate decisions when applicable and publish",
                owner: "workflow.py · reporting.py",
                detail:
                    "For a DismissalDecision, verify the recommendation is route-permitted. Then atomically write authoritative report.json and rendered report.md for either decision or lifecycle result.",
                final: true,
            },
        ],
    },
    {
        id: "live-dismissal",
        title: "Live GHEC dismissal review",
        subtitle:
            "Read a current dismissal request, use immutable repository evidence when needed, and never write back to GitHub.",
        command:
            "DEPENDABOT_GITHUB_TOKEN=<token> uv run dependabot-validator-grunt review-dismissal --request <request-url>",
        labels: ["live_ghec", "dismissal", "credential roles"],
        stages: [
            {
                title: "Validate target, policy, and credentials",
                owner: "main.py · workflow.py",
                detail:
                    "Load invocation-directory .env values, normalize inputs, reject invalid combinations, and assign credentials to GitHub and Copilot roles.",
            },
            {
                title: "Fetch and normalize the dismissal request",
                owner: "github.py · workflow.py",
                detail:
                    "Read the attested request first. Operator reason or justification values are fallback-only and never overwrite non-empty GitHub fields.",
            },
            {
                title: "Check request lifecycle before archive collection",
                owner: "workflow.py",
                detail:
                    "A terminal request takes a cheaper metadata-only path; a pending request needs the immutable repository snapshot.",
                branches: [
                    {
                        label: "Not pending or expired",
                        result:
                            "Fetch alert, repository, branch, and commit metadata only; skip tarball, npm evidence, Copilot, drift re-fetch, and route validation, then publish the lifecycle result.",
                        tone: "safe",
                    },
                    {
                        label: "Pending",
                        result: "Fetch alert/repository/branch, download the commit-pinned tarball, and safely extract the snapshot.",
                    },
                ],
            },
            {
                title: "Collect npm evidence for pending requests",
                owner: "github.py · npm.py · models.py",
                detail:
                    "Inspect the immutable snapshot, record included/excluded paths, and collect dependency instances. Every path, including terminal lifecycle, still writes input/evidence artifacts and a typed bundle.",
                optional: true,
            },
            {
                title: "Run deterministic dismissal rules",
                owner: "deterministic.py",
                detail:
                    "Resolve terminal routes and closed non-applicability proofs before creating any model task.",
                branches: [
                    {
                        label: "Final decision",
                        result: "Skip Copilot and continue to live drift validation.",
                        tone: "safe",
                    },
                    {
                        label: "AgentTask",
                        result: "A COPILOT_GITHUB_TOKEN is required; missing credentials fail configuration with exit 2.",
                        tone: "agent",
                    },
                ],
            },
            {
                title: "Run and validate the bounded Copilot investigation",
                owner: "copilot.py · copilot_assets.py · copilot_tools.py · agentic.py",
                detail:
                    "Create an empty-mode session, verify exact assets and tools, then validate the investigator finding's identity, permissions, schema, and citations.",
                optional: true,
                branches: [
                    {
                        label: "Valid finding",
                        result: "Continue to optional judge review.",
                        tone: "agent",
                    },
                    {
                        label: "Invalid finding",
                        result: "Retry within the shared budget or stop with an explicit Copilot failure.",
                        tone: "warning",
                    },
                    {
                        label: "SDK failure, timeout, or malformed output",
                        result: "Preserve failure/raw artifacts and stop with exit 6.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Challenge a real-model finding",
                owner: "judge.py",
                detail:
                    "Run one no-tool evidence/applicability review. A valid replacement stays within the original task and citation set.",
                optional: true,
                branches: [
                    {
                        label: "Accept or valid replacement",
                        result: "Continue with the selected validated finding.",
                        tone: "agent",
                    },
                    {
                        label: "Judge failure",
                        result: "Record the failure and retain the valid primary finding.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Reconcile the selected finding",
                owner: "deterministic.py",
                detail:
                    "After optional judge review, independently prove permitted outcomes and fail closed when approval evidence is insufficient.",
                optional: true,
            },
            {
                title: "Re-fetch pending request and alert state",
                owner: "github.py · workflow.py",
                detail:
                    "Compare current observable state with the snapshots used for analysis.",
                optional: true,
                branches: [
                    {
                        label: "Drift detected",
                        result: "Publish a stale lifecycle result identifying request or alert changes.",
                        tone: "warning",
                    },
                    {
                        label: "Unchanged",
                        result: "Keep the deterministic or reconciled decision.",
                        tone: "safe",
                    },
                ],
            },
            {
                title: "Validate policy and publish locally",
                owner: "workflow.py · reporting.py",
                detail:
                    "Perform final schema and route checks, then atomically write report.json and report.md. No GitHub mutation occurs.",
                final: true,
            },
        ],
    },
    {
        id: "offline-triage",
        title: "Offline alert triage",
        subtitle:
            "Evaluate a fixture alert deterministically, with optional scripted or real agent refinement.",
        command:
            "uv run dependabot-validator-grunt triage-alert --offline-fixture <case-directory>",
        labels: ["offline_fixture", "triage", "alert only"],
        stages: [
            {
                title: "Validate CLI configuration",
                owner: "main.py",
                detail:
                    "Reject live --repo/--alert inputs mixed with a fixture. --model explicitly selects real Copilot and requires its credential.",
            },
            {
                title: "Load fixture, policy, snapshot, and npm evidence",
                owner: "workflow.py · policy.py · npm.py",
                detail:
                    "Build one typed EvidenceBundle and write input.json plus evidence.json before reasoning.",
            },
            {
                title: "Create the deterministic triage baseline",
                owner: "deterministic.py",
                detail:
                    "Map complete absence to does_not_apply/none, unaffected versions to does_not_apply/none, vulnerable instances to applies/remediate, and incomplete evidence to human_review/investigate.",
            },
            {
                title: "Decide whether agent refinement can run",
                owner: "workflow.py",
                detail:
                    "Deterministic does_not_apply and staged Yarn/pnpm applies results are terminal. npm applies and human_review baselines require agent-response.json or an explicitly selected real model turn.",
                branches: [
                    {
                        label: "Terminal deterministic result",
                        result: "Skip the agent for does_not_apply or staged Yarn/pnpm applies.",
                        tone: "safe",
                    },
                    {
                        label: "No agent boundary",
                        result: "Fail configuration rather than publish a non-terminal baseline.",
                    },
                    {
                        label: "Model turn available",
                        result: "Create a typed triage AgentTask and continue to validated Python reconciliation.",
                        tone: "agent",
                    },
                ],
            },
            {
                title: "Validate investigator evidence",
                owner: "copilot.py · agentic.py",
                detail:
                    "When a model turn ran, validate identities, permissions, schema, and citations.",
                optional: true,
                branches: [
                    {
                        label: "Valid finding",
                        result: "Continue to optional judge review.",
                        tone: "agent",
                    },
                    {
                        label: "Invalid finding",
                        result: "Retry within the shared budget or stop with an explicit Copilot failure.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Challenge a real-model finding",
                owner: "judge.py",
                detail:
                    "Real Copilot findings receive one no-tool evidence/applicability review. Scripted fixture turns skip this stage.",
                optional: true,
                branches: [
                    {
                        label: "Accept or valid replacement",
                        result: "Pass the selected validated finding to deterministic reconciliation.",
                        tone: "agent",
                    },
                    {
                        label: "Judge failure",
                        result: "Record judge-review.json and retain the valid primary finding.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Reconcile the selected finding",
                owner: "deterministic.py",
                detail:
                    "After optional judge review, independently prove permitted outcomes and map the result into triage vocabulary.",
                optional: true,
            },
            {
                title: "Re-read the alert fixture",
                owner: "workflow.py",
                detail:
                    "Use post-analysis-alert.json when present and compare semantic fields with the analyzed alert.",
                branches: [
                    {
                        label: "Alert changed",
                        result: "Fail validation with exit 7; triage does not publish a stale result.",
                        tone: "warning",
                    },
                    {
                        label: "Unchanged",
                        result: "Continue with the baseline or reconciled triage result.",
                        tone: "safe",
                    },
                ],
            },
            {
                title: "Publish the triage report",
                owner: "reporting.py",
                detail:
                    "Atomically write report.json and report.md with assessment, action, priority, evidence identity, and model identity.",
                final: true,
            },
        ],
    },
    {
        id: "live-triage",
        title: "Live GHEC alert triage",
        subtitle:
            "Collect a commit-pinned repository snapshot and send only non-terminal baselines to Copilot.",
        command:
            "DEPENDABOT_GITHUB_TOKEN=<token> uv run dependabot-validator-grunt triage-alert --repo OWNER/REPO --alert NUMBER",
        labels: ["live_ghec", "triage", "application-controlled agent routing"],
        stages: [
            {
                title: "Validate target, options, and credential roles",
                owner: "main.py · workflow.py",
                detail:
                    "Require --repo plus --alert. --model selects a runtime model, while trusted routing decides whether Copilot runs.",
            },
            {
                title: "Collect the immutable live snapshot",
                owner: "github.py",
                detail:
                    "Fetch alert and repository metadata, resolve the default-branch commit SHA, download the bounded tarball, and safely extract allowed files.",
            },
            {
                title: "Build npm evidence and deterministic baseline",
                owner: "npm.py · deterministic.py",
                detail:
                    "Record every relevant package instance and consumer, then choose does_not_apply, applies/remediate, or human_review/investigate.",
            },
            {
                title: "Apply the model gate",
                owner: "workflow.py",
                detail:
                    "Skip Copilot for deterministic does_not_apply and staged Yarn/pnpm applies results. npm applies and human_review baselines require the bounded model boundary.",
                branches: [
                    {
                        label: "Terminal deterministic result",
                        result: "Skip Copilot and keep the deterministic result.",
                        tone: "safe",
                    },
                    {
                        label: "Missing Copilot boundary",
                        result: "Fail configuration before publishing a report.",
                    },
                    {
                        label: "Agent-required route",
                        result: "Run the exact bounded custom agent and continue to validated Python reconciliation.",
                        tone: "agent",
                    },
                ],
            },
            {
                title: "Validate investigator evidence",
                owner: "copilot.py · agentic.py",
                detail:
                    "Accept only identity-bound, citation-backed, policy-permitted findings for optional judge review.",
                optional: true,
                branches: [
                    {
                        label: "Valid finding",
                        result: "Continue to optional judge review.",
                        tone: "agent",
                    },
                    {
                        label: "Invalid finding",
                        result: "Retry within the shared budget or stop with an explicit Copilot failure.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Challenge the real-model finding",
                owner: "judge.py",
                detail:
                    "Run one no-tool evidence/applicability review before deterministic reconciliation.",
                optional: true,
                branches: [
                    {
                        label: "Accept or valid replacement",
                        result: "Continue with the selected validated finding.",
                        tone: "agent",
                    },
                    {
                        label: "Judge failure",
                        result: "Record the failure and retain the valid primary finding.",
                        tone: "warning",
                    },
                ],
            },
            {
                title: "Reconcile the selected finding",
                owner: "deterministic.py",
                detail:
                    "After optional judge review, independently prove permitted outcomes and map the result into triage vocabulary.",
                optional: true,
            },
            {
                title: "Re-fetch the live alert",
                owner: "github.py · workflow.py",
                detail:
                    "Compare current alert semantics with the alert used to build evidence.",
                branches: [
                    {
                        label: "Alert changed",
                        result: "Fail validation with exit 7; do not publish a stale triage report.",
                        tone: "warning",
                    },
                    {
                        label: "Unchanged",
                        result: "Continue with the deterministic or reconciled result.",
                        tone: "safe",
                    },
                ],
            },
            {
                title: "Publish locally",
                owner: "reporting.py",
                detail:
                    "Atomically write authoritative JSON and safe Markdown. GitHub remains read-only.",
                final: true,
            },
        ],
    },
];

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function command(value) {
    return `<div class="command"><code>${escapeHtml(value)}</code><button type="button" data-copy="${escapeHtml(value)}" aria-label="Copy command">Copy</button></div>`;
}

function file(value, description) {
    return `<div class="file-row"><code>${escapeHtml(value)}</code><span>${escapeHtml(description)}</span></div>`;
}

function pill(value, tone = "") {
    return `<span class="pill ${tone}">${escapeHtml(value)}</span>`;
}

function flowNode(title, detail, tone = "") {
    return `<div class="flow-node ${tone}"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
}

function renderApplicationStage(stage, index) {
    const branches = stage.branches
        ? `<div class="application-branches">${stage.branches
              .map(
                  (branch) =>
                      `<div class="application-branch ${escapeHtml(branch.tone ?? "")}"><strong>${escapeHtml(branch.label)}</strong><span>${escapeHtml(branch.result)}</span></div>`,
              )
              .join("")}</div>`
        : "";
    const classes = [
        "application-stage",
        stage.optional ? "optional" : "",
        stage.final ? "final" : "",
    ]
        .filter(Boolean)
        .join(" ");
    return `<div class="${classes}">
      <div class="stage-marker">${index + 1}</div>
      <div class="stage-body">
        <div class="stage-heading"><h3>${escapeHtml(stage.title)}</h3><code>${escapeHtml(stage.owner)}</code></div>
        <p>${escapeHtml(stage.detail)}</p>
        ${branches}
      </div>
    </div>`;
}

function renderUseCaseFlow(useCase, isActive) {
    return `<article class="use-case-panel${isActive ? " active" : ""}" data-use-case-panel="${escapeHtml(useCase.id)}">
      <header class="use-case-header">
        <div>
          <div class="pill-row">${useCase.labels.map((label) => pill(label)).join("")}</div>
          <h3>${escapeHtml(useCase.title)}</h3>
          <p>${escapeHtml(useCase.subtitle)}</p>
        </div>
        ${command(useCase.command)}
      </header>
      <div class="application-flow">${useCase.stages
          .map((stage, index) => renderApplicationStage(stage, index))
          .join("")}</div>
    </article>`;
}

function renderNavigation(initialTopic) {
    return topics
        .map(
            ([id, label]) =>
                `<button type="button" class="nav-item${id === initialTopic ? " active" : ""}" data-topic="${id}">${escapeHtml(label)}</button>`,
        )
        .join("");
}

function sectionAttributes(topic, initialTopic) {
    return `class="topic${topic === initialTopic ? " active" : ""}" data-panel="${topic}"`;
}

function renderOverview(initialTopic) {
    return `
      <section ${sectionAttributes("overview", initialTopic)}>
        <div class="eyebrow">Mental model</div>
        <h2>Evidence first. Agent second. Python decides.</h2>
        <p class="lead">This CLI reviews one Dependabot dismissal request or triages one alert. It combines deterministic npm facts with a tightly bounded Copilot investigation, then publishes local evidence-backed reports.</p>
        <div class="callout strong"><strong>The invariant:</strong> Copilot can investigate and propose. It cannot authorize an outcome, expand permissions, write to GitHub, or publish a report directly.</div>
        <div class="metric-grid">
          <article><span class="metric">2</span><strong>workflows</strong><p><code>review-dismissal</code> and <code>triage-alert</code></p></article>
          <article><span class="metric">4</span><strong>agent tools</strong><p><code>list_files</code>, <code>read_file</code>, <code>search</code>, <code>analyze_reachability</code></p></article>
          <article><span class="metric">0</span><strong>GitHub writes</strong><p>Reports stay in the selected local output directory.</p></article>
        </div>
        <h3>Decision flow</h3>
        <div class="flow horizontal">
          ${flowNode("Input", "Live GHEC target or offline fixture")}
          <span class="arrow">→</span>
          ${flowNode("Evidence", "Typed alert, repository, and npm facts")}
          <span class="arrow">→</span>
          ${flowNode("Rules", "Deterministic policy and proof engine", "trusted")}
          <span class="arrow">→</span>
          ${flowNode("Agent", "Optional read-only investigation", "agent")}
          <span class="arrow">→</span>
          ${flowNode("Judge", "Optional no-tool critic review", "agent")}
          <span class="arrow">→</span>
          ${flowNode("Report", "Validated local JSON and Markdown", "trusted")}
        </div>
        <h3>Minimum reading path</h3>
        <div class="file-list">
          ${file("README.md", "Product overview, common commands, and customization map.")}
          ${file("docs/architecture.md", "Module ownership, trust boundaries, and end-to-end flow.")}
          ${file("docs/README.md", "Select the change-specific contract, reference, or ADR.")}
          ${file("docs/development.md", "Setup, canonical checks, and iteration workflow.")}
          ${file(".github/LESSONS_LEARNED.md", "Topic-indexed corrections; read only relevant entries.")}
        </div>
      </section>`;
}

function renderRun(initialTopic) {
    return `
      <section ${sectionAttributes("run", initialTopic)}>
        <div class="eyebrow">Developer runbook</div>
        <h2>Start offline, then cross one boundary at a time.</h2>
        <div class="two-column">
          <div>
            <h3>1. Set up</h3>
            ${command("uv sync --all-groups --locked")}
            ${command("uv run python -m copilot download-runtime")}
            <h3>2. Run credential-free fixtures</h3>
            ${command("uv run dependabot-validator-grunt review-dismissal --offline-fixture examples/offline-cases/not-used-absent")}
            ${command("uv run dependabot-validator-grunt triage-alert --offline-fixture examples/offline-cases/triage-vulnerable")}
            <h3>3. Exercise the real Copilot boundary</h3>
            ${command("COPILOT_GITHUB_TOKEN=<copilot-user-pat> uv run dependabot-validator-grunt review-dismissal --offline-fixture examples/offline-cases/tolerable-risk --model <runtime-model-id>")}
          </div>
          <div>
            <h3>Run against GitHub Enterprise Cloud</h3>
            ${command("DEPENDABOT_GITHUB_TOKEN=<github-token> uv run dependabot-validator-grunt review-dismissal --request https://github.com/OWNER/REPO/security/dependabot/ALERT_NUMBER")}
            ${command("DEPENDABOT_GITHUB_TOKEN=<github-token> uv run dependabot-validator-grunt triage-alert --repo OWNER/REPO --alert ALERT_NUMBER")}
            <div class="callout warning"><strong>Credential roles:</strong> live GitHub collection uses <code>DEPENDABOT_GITHUB_TOKEN</code>; real Copilot uses <code>COPILOT_GITHUB_TOKEN</code>. The CLI loads both from <code>./.env</code> without overriding exported values. One value may serve both roles, but distinct least-privileged credentials reduce revocation and exposure blast radius.</div>
            <h3>Copilot mode matrix</h3>
            <div class="file-list">
              ${file("Offline dismissal or triage", "Use the scripted fixture response by default. --model explicitly selects real Copilot and overrides the script.")}
              ${file("Live dismissal review", "Deterministic routing selects agent-required routes; --model only selects the runtime model.")}
              ${file("Live alert triage", "Deterministic does_not_apply and staged Yarn/pnpm applies skip Copilot; npm applies and human_review routes use the real boundary.")}
            </div>
            <h3>Shared controls</h3>
            <div class="pill-row">${pill("--output <directory>")}${pill("--policy <file>")}${pill("--model <runtime-model-id>")}</div>
            <p>Reports go to <code>./reports</code> by default. Use <code>--help</code> for the complete option contract.</p>
          </div>
        </div>
      </section>`;
}

function renderFlows(initialTopic) {
    return `
      <section ${sectionAttributes("flows", initialTopic)}>
        <div class="eyebrow">End-to-end execution</div>
        <h2>See the complete application flow for every use case.</h2>
        <p class="lead">Choose an entry path to trace validation, evidence collection, deterministic reasoning, optional agent analysis, state drift, and local publication.</p>
        <div class="flow-legend">
          <span><i class="legend-dot deterministic"></i> standard stage</span>
          <span><i class="legend-dot safe"></i> terminal or accepted deterministic branch</span>
          <span><i class="legend-dot agent"></i> conditional stage or agent path</span>
          <span><i class="legend-dot warning"></i> stale or failure path</span>
        </div>
        <div class="use-case-selector" aria-label="Application use cases">
          ${applicationFlows
              .map(
                  (useCase, index) =>
                      `<button type="button" aria-pressed="${index === 0 ? "true" : "false"}" class="use-case-button${index === 0 ? " active" : ""}" data-use-case="${escapeHtml(useCase.id)}">${escapeHtml(useCase.title)}</button>`,
              )
              .join("")}
        </div>
        <div class="use-case-panels">
          ${applicationFlows
              .map((useCase, index) => renderUseCaseFlow(useCase, index === 0))
              .join("")}
        </div>
        <div class="common-rail">
          <strong>Common failure rail</strong>
          <div class="exit-grid">
            ${pill("2 configuration")}
            ${pill("3 GitHub auth")}
            ${pill("4 collection")}
            ${pill("5 npm evidence")}
            ${pill("6 Copilot")}
            ${pill("7 reconciliation / validation")}
            ${pill("8 publication")}
          </div>
          <p>Failures are stage-classified. A failed run does not overwrite a successful report, and untrusted model payloads remain only in dedicated raw-output artifacts.</p>
        </div>
      </section>`;
}

function renderArchitecture(initialTopic) {
    return `
      <section ${sectionAttributes("architecture", initialTopic)}>
        <div class="eyebrow">System architecture</div>
        <h2>A single CLI process with two reasoning engines.</h2>
        <p class="lead">Purpose-based modules keep deterministic facts, model-facing assets, external boundaries, and report publication separate without introducing a framework.</p>
        <div class="callout"><strong>Python package root:</strong> every module named below lives under <code>src/dependabot_validator_grunt/</code>.</div>
        <div class="architecture">
          <div class="lane">
            <div class="lane-label">Trusted control plane</div>
            ${flowNode("main.py", "Typer parsing and dependency construction")}
            ${flowNode("workflow.py", "Collection, orchestration, drift checks, publication")}
            ${flowNode("models.py", "Frozen serializable evidence, tasks, findings, results")}
            ${flowNode("policy.py", "Versioned policy loading and startup validation")}
            ${flowNode("deterministic.py", "Routing, proofs, permitted outcomes, reconciliation", "trusted")}
            ${flowNode("agentic.py", "Bounded snapshot tools and untrusted-finding validation", "trusted")}
            ${flowNode("reachability.py", "Fixed bounded ast-grep subprocess boundary", "trusted")}
            ${flowNode("judge.py", "No-tool two-critic review and replacement validation", "trusted")}
            ${flowNode("reporting.py", "Atomic validated report.json and report.md", "trusted")}
          </div>
          <div class="lane boundary">
            <div class="lane-label">External boundaries</div>
            ${flowNode("github.py", "Read-only GHEC API and immutable repository snapshot")}
            ${flowNode("npm.py", "Project selection and npm-ecosystem adapter dispatch")}
            ${flowNode("dependency_graph.py", "Manager-neutral graph projection")}
            ${flowNode("yarn.py", "Bounded Yarn Classic v1 parsing")}
            ${flowNode("pnpm.py", "Bounded pnpm lockfile v9.0 parsing")}
            ${flowNode("copilot.py", "SDK lifecycle, exact agent selection, retries, events")}
            ${flowNode("copilot_assets.py", "Strict declarative asset loading and validation")}
            ${flowNode("copilot_tools.py", "Pydantic SDK tool inputs and handler adapters")}
          </div>
          <div class="lane agent-lane">
            <div class="lane-label">Model-facing package data</div>
            ${flowNode("system-prompts/", "Session-wide trust invariants", "agent")}
            ${flowNode("agents/", "Role, output contract, tool and skill bindings", "agent")}
            ${flowNode("prompts/", "One task-dispatch template per role", "agent")}
            ${flowNode("skills/", "Investigation and review methodology", "agent")}
            ${flowNode("tools/", "Names and model-facing descriptions", "agent")}
          </div>
        </div>
        <div class="callout"><strong>Boundary rule:</strong> declarative assets describe behavior but cannot grant tools, authorize outcomes, or replace deterministic validation.</div>
      </section>`;
}

function renderCustomize(initialTopic) {
    return `
      <section ${sectionAttributes("customize", initialTopic)}>
        <div class="eyebrow">Ownership map</div>
        <h2>Customize the smallest surface that owns the behavior.</h2>
        <div class="ownership">
          <article>
            <span class="number">01</span><h3>Policy</h3>
            <code>src/dependabot_validator_grunt/policies/default.json</code>
            <p>Routes, limits, enabled rule IDs, confidence threshold, and permitted outcome/code groups.</p>
            <div class="guardrail">Declarative only. Executable rules do not belong here.</div>
          </article>
          <article>
            <span class="number">02</span><h3>Deterministic engine</h3>
            <code>src/dependabot_validator_grunt/deterministic.py</code>
            <p>Proof rules, routing, authorization, and final reconciliation.</p>
            <div class="guardrail">Use this for enforceable decision behavior.</div>
          </article>
          <article>
            <span class="number">03</span><h3>Agent identity</h3>
            <code>src/dependabot_validator_grunt/agents/dependency-risk-investigator/agent.json</code><br/><code>src/dependabot_validator_grunt/agents/dependency-risk-judge/agent.json</code>
            <p>Each custom-agent name plus its exact tool and skill bindings.</p>
            <div class="guardrail"><code>infer</code> stays false; bindings must match runtime allowlists.</div>
          </article>
          <article>
            <span class="number">04</span><h3>Agent contract</h3>
            <code>src/dependabot_validator_grunt/agents/dependency-risk-investigator/prompt.md</code><br/><code>src/dependabot_validator_grunt/agents/dependency-risk-judge/prompt.md</code>
            <p>Role-specific structured output contracts and restrictions.</p>
            <div class="guardrail">Do not move policy authority into prose.</div>
          </article>
          <article>
            <span class="number">05</span><h3>Session safety</h3>
            <code>src/dependabot_validator_grunt/system-prompts/dependency-risk-session.md</code><br/><code>src/dependabot_validator_grunt/system-prompts/dependency-risk-judge.md</code>
            <p>Per-session trust boundaries and prompt-injection resistance.</p>
            <div class="guardrail">Append-mode system instructions are required.</div>
          </article>
          <article>
            <span class="number">06</span><h3>Methodology</h3>
            <code>src/dependabot_validator_grunt/skills/dependency-risk-analysis/SKILL.md</code><br/><code>src/dependabot_validator_grunt/skills/dependency-risk-review/SKILL.md</code>
            <p>Reusable investigation and two-lens review methodology.</p>
            <div class="guardrail">Each runtime must load exactly its role's custom-source skill.</div>
          </article>
          <article>
            <span class="number">07</span><h3>Task dispatch</h3>
            <code>src/dependabot_validator_grunt/prompts/dependency-investigation.md.tmpl</code><br/><code>src/dependabot_validator_grunt/prompts/dependency-judge.md.tmpl</code>
            <p>Minimal dispatch around the validated task or frozen review context.</p>
            <div class="guardrail">Keep deterministic facts in the task, not inferred from prose.</div>
          </article>
          <article>
            <span class="number">08</span><h3>Tools</h3>
            <code>src/dependabot_validator_grunt/tools/repository-tools.json</code><br/><code>src/dependabot_validator_grunt/copilot_tools.py</code>
            <p>Metadata is declarative; Pydantic SDK schemas and adapters stay in Python.</p>
            <div class="guardrail">Tool names must exactly match agent and session allowlists.</div>
          </article>
          <article>
            <span class="number">09</span><h3>Tool bounds and finding validation</h3>
            <code>src/dependabot_validator_grunt/agentic.py</code>
            <p>Path denial, byte and result budgets, digest-bound observations, and validation of untrusted agent findings.</p>
            <div class="guardrail">Tighten the trusted boundary here, not in model-facing prose.</div>
          </article>
        </div>
        <div class="callout strong"><strong>Rule of thumb:</strong> if a change affects final outcomes, put it in policy or deterministic Python and test it there. Prompts and skills can guide investigation, but they cannot make a claim trustworthy.</div>
      </section>`;
}

function renderSafety(initialTopic) {
    return `
      <section ${sectionAttributes("safety", initialTopic)}>
        <div class="eyebrow">Least privilege</div>
        <h2>The agent operates inside a deliberately narrow box.</h2>
        <div class="safety-grid">
          <article class="allowed">
            <h3>Allowed</h3>
            <ul>
              <li>Receive one typed <code>AgentTask</code>.</li>
              <li>List bounded snapshot files.</li>
              <li>Read bounded UTF-8 files.</li>
              <li>Search literal text and cite digest-bound observations.</li>
              <li>Run the fixed, bounded structural reachability analysis.</li>
              <li>Return one schema-validated finding.</li>
            </ul>
          </article>
          <article class="denied">
            <h3>Denied</h3>
            <ul>
              <li>Command shells, subprocesses, package managers, writes, or arbitrary network access.</li>
              <li>GitHub mutations, MCP, plugins, memory, session store, or host git operations.</li>
              <li>Repository, personal, inherited, plugin, or built-in agents and skills.</li>
              <li>Credential-like files and repository-provided agent controls.</li>
              <li>Outcomes or reason codes outside the typed permission group.</li>
            </ul>
          </article>
        </div>
        <h3>Defense in depth</h3>
        <div class="defense">
          <div><span>1</span><strong>Empty SDK mode</strong><p>Nothing is available unless the session explicitly declares it.</p></div>
          <div><span>2</span><strong>Exact assets</strong><p>Runtime events must confirm the selected custom agent and one custom-source skill.</p></div>
          <div><span>3</span><strong>Bounded tools</strong><p>Paths, byte budgets, result counts, file types, and snapshot boundaries are checked.</p></div>
          <div><span>4</span><strong>Untrusted output</strong><p>Finding identities, citations, proposals, confidence, and flags are validated.</p></div>
          <div><span>5</span><strong>Python reconciliation</strong><p>Load-bearing approval predicates are independently re-proven.</p></div>
          <div><span>6</span><strong>Safe publication</strong><p>Atomic local writes prevent failed runs from replacing approved reports.</p></div>
        </div>
        <div class="callout warning"><strong>Never weaken a guardrail just to make an agent answer pass.</strong> An unsupported or unverifiable claim must fail closed to <code>human_review</code> or an explicit workflow failure.</div>
      </section>`;
}

function renderChange(initialTopic) {
    return `
      <section ${sectionAttributes("change", initialTopic)}>
        <div class="eyebrow">Engineering workflow</div>
        <h2>Change contracts before behavior, and prove every checklist item.</h2>
        <div class="timeline">
          <div><span>1</span><section><h3>Orient selectively</h3><p>Read <code>README.md</code>, architecture, and relevant source/tests. Use the docs, ADR, and lessons indexes to select only change-relevant context.</p></section></div>
          <div><span>2</span><section><h3>Update the contract first when needed</h3><p>Workflow inputs, evidence, stages, permissions, outputs, failures, validation, or publication changes begin in <code>docs/workflow-contract.md</code>.</p></section></div>
          <div><span>3</span><section><h3>Check whether an ADR is required</h3><p>Core module ownership, workflow invariants, permission model, or validation/publication policy changes require a new ADR.</p></section></div>
          <div><span>4</span><section><h3>Implement the smallest complete change</h3><p>Keep tests offline, fake Copilot and network boundaries, and add production-shaped negative cases.</p></section></div>
          <div><span>5</span><section><h3>Review independently</h3><p>Use a separate reviewer context for concrete logic, safety, and design feedback.</p></section></div>
          <div><span>6</span><section><h3>Run the complete baseline</h3><div class="compact-commands">
            ${command("uv run pytest")}
            ${command("uv run ruff check .")}
            ${command("uv run ruff format --check .")}
            ${command("uv run pyright")}
            ${command("uv build")}
          </div></section></div>
        </div>
        <h3>Failure exits</h3>
        <div class="exit-grid">
          ${pill("0 report created", "good")}
          ${pill("2 configuration")}
          ${pill("3 GitHub auth")}
          ${pill("4 collection")}
          ${pill("5 npm evidence")}
          ${pill("6 Copilot")}
          ${pill("7 reconciliation / validation")}
          ${pill("8 publication")}
        </div>
      </section>`;
}

function renderTopics(initialTopic) {
    return [
        renderOverview(initialTopic),
        renderRun(initialTopic),
        renderFlows(initialTopic),
        renderArchitecture(initialTopic),
        renderCustomize(initialTopic),
        renderSafety(initialTopic),
        renderChange(initialTopic),
    ].join("");
}

export function renderOnboardingHtml({ instanceId, initialTopic }) {
    const safeInitialTopic = Object.hasOwn(topicSummaries, initialTopic)
        ? initialTopic
        : "overview";
    return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Dependabot Validator Grunt onboarding</title>
    <style>
      :root { color-scheme: light dark; }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: var(--background-color-default, #0d1117);
        color: var(--text-color-default, #f0f6fc);
        font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
        font-size: var(--text-body-medium, 14px);
        line-height: var(--leading-body-medium, 1.5);
      }
      button { font: inherit; }
      code {
        font-family: var(--font-mono, "SFMono-Regular", Consolas, monospace);
        font-size: var(--text-code-inline, 12px);
      }
      .shell { min-height: 100vh; display: grid; grid-template-columns: 240px minmax(0, 1fr); }
      aside {
        position: sticky; top: 0; height: 100vh; padding: 28px 18px;
        border-right: 1px solid var(--border-color-default, #30363d);
        background: color-mix(in srgb, var(--background-color-default, #0d1117) 94%, var(--true-color-blue, #58a6ff) 6%);
      }
      .brand { display: flex; gap: 12px; align-items: center; margin-bottom: 28px; }
      .logo {
        width: 38px; height: 38px; display: grid; place-items: center; border-radius: 10px;
        background: var(--true-color-blue, #0969da); color: var(--color-white, #fff);
        font-weight: var(--font-weight-semibold, 600);
      }
      .brand strong { display: block; font-size: 15px; line-height: 1.2; }
      .brand small { color: var(--text-color-muted, #8c959f); }
      nav { display: grid; gap: 6px; }
      .nav-item {
        border: 0; border-radius: 8px; padding: 9px 12px; text-align: left; cursor: pointer;
        background: transparent; color: var(--text-color-muted, #8c959f);
      }
      .nav-item:hover, .nav-item.active {
        background: color-mix(in srgb, var(--true-color-blue, #58a6ff) 16%, transparent);
        color: var(--text-color-default, #f0f6fc);
      }
      .aside-footer {
        position: absolute; left: 18px; right: 18px; bottom: 22px;
        color: var(--text-color-muted, #8c959f); font-size: 11px;
      }
      main { padding: 44px clamp(26px, 5vw, 72px) 72px; max-width: 1440px; width: 100%; }
      .topic { display: none; animation: appear 180ms ease-out; }
      .topic.active { display: block; }
      @keyframes appear { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
      .eyebrow { color: var(--true-color-blue, #58a6ff); font-weight: 600; text-transform: uppercase; letter-spacing: .12em; font-size: 11px; }
      h2 { max-width: 900px; margin: 8px 0 14px; font-size: clamp(28px, 4vw, 46px); line-height: 1.08; letter-spacing: -.035em; }
      h3 { margin: 28px 0 12px; font-size: 16px; }
      p { color: var(--text-color-muted, #8c959f); }
      .lead { max-width: 900px; font-size: 17px; line-height: 1.6; margin-bottom: 24px; }
      .callout {
        margin: 22px 0; padding: 16px 18px; border: 1px solid var(--border-color-default, #30363d);
        border-left: 3px solid var(--true-color-blue, #58a6ff); border-radius: 8px;
        background: color-mix(in srgb, var(--true-color-blue-muted, #1f6feb) 12%, transparent);
      }
      .callout.strong { border-left-color: var(--true-color-blue, #58a6ff); }
      .callout.warning {
        border-left-color: var(--true-color-red, #f85149);
        background: color-mix(in srgb, var(--true-color-red-muted, #da3633) 10%, transparent);
      }
      .metric-grid, .ownership, .defense { display: grid; gap: 14px; }
      .metric-grid { grid-template-columns: repeat(3, 1fr); margin: 28px 0; }
      .metric-grid article, .ownership article, .defense > div, .safety-grid article {
        border: 1px solid var(--border-color-default, #30363d); border-radius: 10px; padding: 18px;
        background: color-mix(in srgb, var(--background-color-default, #0d1117) 96%, var(--text-color-default, #f0f6fc) 4%);
      }
      .metric { display: block; font-size: 30px; font-weight: 700; color: var(--true-color-blue, #58a6ff); }
      .metric-grid p { margin-bottom: 0; }
      .flow.horizontal { display: flex; align-items: stretch; gap: 8px; overflow-x: auto; padding-bottom: 8px; }
      .flow-node {
        min-width: 155px; flex: 1; display: flex; flex-direction: column; gap: 5px;
        border: 1px solid var(--border-color-default, #30363d); border-radius: 9px; padding: 14px;
      }
      .flow-node span { color: var(--text-color-muted, #8c959f); font-size: 12px; }
      .flow-node.trusted { border-color: color-mix(in srgb, var(--true-color-blue, #58a6ff) 58%, var(--border-color-default, #30363d)); }
      .flow-node.agent { border-style: dashed; }
      .arrow { align-self: center; color: var(--text-color-muted, #8c959f); }
      .file-list { display: grid; gap: 8px; }
      .file-row { display: grid; grid-template-columns: minmax(220px, .8fr) 2fr; gap: 14px; padding: 11px 0; border-bottom: 1px solid var(--border-color-default, #30363d); }
      .file-row span { color: var(--text-color-muted, #8c959f); }
      .two-column { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(24px, 5vw, 64px); }
      .command {
        display: flex; align-items: flex-start; gap: 8px; margin: 8px 0; padding: 10px 10px 10px 12px;
        border: 1px solid var(--border-color-default, #30363d); border-radius: 8px;
        background: color-mix(in srgb, var(--background-color-default, #0d1117) 92%, black 8%);
      }
      .command code { flex: 1; min-width: 0; overflow-wrap: anywhere; color: var(--text-color-default, #f0f6fc); }
      .command button {
        border: 1px solid var(--border-color-default, #30363d); border-radius: 6px; padding: 3px 8px;
        background: transparent; color: var(--text-color-muted, #8c959f); cursor: pointer; font-size: 11px;
      }
      .command button:hover { color: var(--text-color-default, #f0f6fc); border-color: var(--color-focus-outline, #1f6feb); }
      .pill-row, .exit-grid { display: flex; flex-wrap: wrap; gap: 8px; }
      .pill { display: inline-flex; border: 1px solid var(--border-color-default, #30363d); border-radius: 999px; padding: 5px 10px; font-family: var(--font-mono, monospace); font-size: 11px; }
      .pill.good { border-color: color-mix(in srgb, #3fb950 70%, var(--border-color-default, #30363d)); }
      .flow-legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 20px 0; color: var(--text-color-muted, #8c959f); font-size: 12px; }
      .flow-legend span { display: inline-flex; align-items: center; gap: 7px; }
      .legend-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--true-color-blue, #58a6ff); }
      .legend-dot.safe { background: #3fb950; }
      .legend-dot.agent { background: #d29922; }
      .legend-dot.warning { background: var(--true-color-red, #f85149); }
      .use-case-selector {
        display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px;
        margin: 24px 0 18px; padding: 5px; border: 1px solid var(--border-color-default, #30363d);
        border-radius: 11px;
      }
      .use-case-button {
        border: 0; border-radius: 7px; padding: 10px; cursor: pointer;
        background: transparent; color: var(--text-color-muted, #8c959f);
      }
      .use-case-button:hover, .use-case-button.active {
        background: color-mix(in srgb, var(--true-color-blue, #58a6ff) 16%, transparent);
        color: var(--text-color-default, #f0f6fc);
      }
      .use-case-panel { display: none; }
      .use-case-panel.active { display: block; animation: appear 180ms ease-out; }
      .use-case-header {
        display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, .8fr); gap: 28px;
        align-items: start; padding: 20px; border: 1px solid var(--border-color-default, #30363d);
        border-radius: 12px 12px 0 0;
        background: color-mix(in srgb, var(--true-color-blue, #58a6ff) 6%, transparent);
      }
      .use-case-header h3 { margin: 12px 0 4px; font-size: 22px; }
      .use-case-header p { margin: 0; }
      .use-case-header .command { margin: 0; }
      .application-flow {
        position: relative; padding: 24px 20px 6px;
        border: 1px solid var(--border-color-default, #30363d); border-top: 0;
        border-radius: 0 0 12px 12px;
      }
      .application-flow::before {
        content: ""; position: absolute; top: 28px; bottom: 40px; left: 37px;
        width: 2px; background: color-mix(in srgb, var(--true-color-blue, #58a6ff) 45%, var(--border-color-default, #30363d));
      }
      .application-stage {
        position: relative; display: grid; grid-template-columns: 36px minmax(0, 1fr); gap: 16px;
        margin-bottom: 18px;
      }
      .stage-marker {
        z-index: 1; display: grid; place-items: center; width: 34px; height: 34px;
        border: 2px solid var(--true-color-blue, #58a6ff); border-radius: 50%;
        background: var(--background-color-default, #0d1117); color: var(--true-color-blue, #58a6ff);
        font-weight: 700;
      }
      .application-stage.optional .stage-marker { border-style: dashed; border-color: #d29922; color: #d29922; }
      .application-stage.final .stage-marker { background: var(--true-color-blue, #58a6ff); color: var(--color-white, #fff); }
      .stage-body {
        padding: 0 0 18px; border-bottom: 1px solid var(--border-color-default, #30363d);
      }
      .application-stage:last-child .stage-body { border-bottom: 0; }
      .stage-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; }
      .stage-heading h3 { margin: 3px 0 5px; }
      .stage-heading code { color: var(--text-color-muted, #8c959f); }
      .stage-body > p { margin: 2px 0 12px; }
      .application-branches { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
      .application-branch {
        display: flex; flex-direction: column; gap: 4px; padding: 11px 12px;
        border: 1px solid var(--border-color-default, #30363d); border-radius: 8px;
        background: color-mix(in srgb, var(--background-color-default, #0d1117) 96%, var(--text-color-default, #f0f6fc) 4%);
      }
      .application-branch span { color: var(--text-color-muted, #8c959f); font-size: 12px; }
      .application-branch.safe { border-left: 3px solid #3fb950; }
      .application-branch.agent { border-left: 3px dashed #d29922; }
      .application-branch.warning { border-left: 3px solid var(--true-color-red, #f85149); }
      .common-rail {
        margin-top: 20px; padding: 17px 19px; border: 1px solid var(--border-color-default, #30363d);
        border-radius: 10px;
      }
      .common-rail .exit-grid { margin-top: 10px; }
      .common-rail p { margin-bottom: 0; }
      .architecture { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 28px 0; }
      .lane { display: grid; gap: 9px; align-content: start; padding: 14px; border-radius: 12px; background: color-mix(in srgb, var(--true-color-blue, #58a6ff) 5%, transparent); }
      .lane.boundary { background: color-mix(in srgb, #a371f7 7%, transparent); }
      .lane.agent-lane { background: color-mix(in srgb, #d29922 7%, transparent); }
      .lane-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--text-color-muted, #8c959f); margin: 2px 2px 5px; }
      .ownership { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 28px; }
      .ownership article { position: relative; padding-top: 44px; }
      .ownership .number { position: absolute; top: 14px; right: 16px; color: var(--text-color-muted, #8c959f); font-family: var(--font-mono, monospace); }
      .ownership h3 { margin: 0 0 5px; }
      .ownership p { min-height: 44px; }
      .guardrail { padding-top: 10px; border-top: 1px solid var(--border-color-default, #30363d); color: var(--text-color-muted, #8c959f); font-size: 12px; }
      .safety-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 26px 0; }
      .safety-grid h3 { margin-top: 0; }
      .safety-grid article.allowed { border-top: 3px solid #3fb950; }
      .safety-grid article.denied { border-top: 3px solid var(--true-color-red, #f85149); }
      ul { padding-left: 20px; }
      li { margin: 9px 0; color: var(--text-color-muted, #8c959f); }
      .defense { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .defense span {
        display: inline-grid; place-items: center; width: 25px; height: 25px; margin-right: 8px;
        border-radius: 50%; background: var(--true-color-blue, #58a6ff); color: var(--color-white, #fff); font-weight: 700;
      }
      .defense p { margin-bottom: 0; }
      .timeline { position: relative; margin-top: 28px; }
      .timeline::before { content: ""; position: absolute; top: 10px; bottom: 10px; left: 16px; width: 1px; background: var(--border-color-default, #30363d); }
      .timeline > div { position: relative; display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 16px; margin-bottom: 20px; }
      .timeline > div > span {
        z-index: 1; display: grid; place-items: center; width: 33px; height: 33px; border-radius: 50%;
        background: var(--true-color-blue, #58a6ff); color: var(--color-white, #fff); font-weight: 700;
      }
      .timeline section { padding: 0 0 8px; }
      .timeline h3 { margin: 3px 0 5px; }
      .timeline p { margin-top: 0; }
      .compact-commands { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 8px; }
      @media (max-width: 900px) {
        .shell { grid-template-columns: 1fr; }
        aside { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border-color-default, #30363d); padding: 16px; }
        .brand { margin-bottom: 12px; }
        nav { display: flex; overflow-x: auto; }
        .nav-item { white-space: nowrap; }
        .aside-footer { display: none; }
        main { padding-top: 30px; }
        .two-column, .architecture, .safety-grid, .use-case-header { grid-template-columns: 1fr; }
        .use-case-selector { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .defense { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
      @media (max-width: 620px) {
        .metric-grid, .ownership, .defense, .compact-commands { grid-template-columns: 1fr; }
        .file-row { grid-template-columns: 1fr; gap: 3px; }
        .use-case-selector, .application-branches { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <aside>
        <div class="brand"><div class="logo">DV</div><div><strong>Dependabot Validator</strong><small>Engineer onboarding</small></div></div>
        <nav aria-label="Onboarding topics">${renderNavigation(safeInitialTopic)}</nav>
        <div class="aside-footer">Project canvas · instance ${escapeHtml(instanceId)}</div>
      </aside>
      <main>${renderTopics(safeInitialTopic)}</main>
    </div>
    <script>
      const initialTopic = ${JSON.stringify(safeInitialTopic)};
      const buttons = [...document.querySelectorAll("[data-topic]")];
      const panels = [...document.querySelectorAll("[data-panel]")];
      function selectTopic(topic) {
        buttons.forEach((button) => button.classList.toggle("active", button.dataset.topic === topic));
        panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === topic));
      }
      buttons.forEach((button) => button.addEventListener("click", () => selectTopic(button.dataset.topic)));
      const useCaseButtons = [...document.querySelectorAll("[data-use-case]")];
      const useCasePanels = [...document.querySelectorAll("[data-use-case-panel]")];
      function selectUseCase(useCase) {
        useCaseButtons.forEach((button) => {
          const selected = button.dataset.useCase === useCase;
          button.classList.toggle("active", selected);
          button.setAttribute("aria-pressed", String(selected));
        });
        useCasePanels.forEach((panel) => panel.classList.toggle("active", panel.dataset.useCasePanel === useCase));
      }
      useCaseButtons.forEach((button) => button.addEventListener("click", () => selectUseCase(button.dataset.useCase)));
      const events = new EventSource("events");
      events.addEventListener("topic", (event) => selectTopic(JSON.parse(event.data)));
      document.querySelectorAll("[data-copy]").forEach((button) => {
        button.addEventListener("click", async () => {
          const previous = button.textContent;
          try {
            await navigator.clipboard.writeText(button.dataset.copy);
            button.textContent = "Copied";
          } catch {
            const code = button.parentElement.querySelector("code");
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(code);
            selection.removeAllRanges();
            selection.addRange(range);
            button.textContent = "Selected";
          }
          setTimeout(() => { button.textContent = previous; }, 1200);
        });
      });
      selectTopic(initialTopic);
    </script>
  </body>
</html>`;
}
