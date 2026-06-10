const API_BASE =
  window.location.protocol === "file:" || window.location.port === "5500"
    ? localStorage.getItem("talentforge_api_base") || "http://127.0.0.1:8010"
    : window.location.origin;

const storedUser = JSON.parse(localStorage.getItem("talentforge_user") || "null");
const legacyCandidateProfiles = localStorage.getItem("talentforge_candidate_profiles") || "[]";
const legacyProfilesBelongToStoredUser = (() => {
  if (!storedUser?.full_name) return false;
  const expectedName = storedUser.full_name.trim().toLocaleLowerCase("tr");
  try {
    return JSON.parse(legacyCandidateProfiles).some(
      (profile) => String(profile?.name || "").trim().toLocaleLowerCase("tr") === expectedName
    );
  } catch {
    return false;
  }
})();
const storedCandidateProfiles =
  (storedUser?.id && localStorage.getItem(`talentforge_candidate_profiles:${storedUser.id}`)) ||
  (legacyProfilesBelongToStoredUser ? legacyCandidateProfiles : null) ||
  "[]";

const state = {
  role: localStorage.getItem("talentforge_role") || "hr",
  token: localStorage.getItem("talentforge_token") || "",
  user: storedUser,
  jobs: [],
  applications: [],
  recommendations: [],
  recommendationsLoadedAt: 0,
  dashboardSummary: null,
  recentSearch: JSON.parse(localStorage.getItem("talentforge_recent_search") || "null"),
  savedSearches: JSON.parse(localStorage.getItem("talentforge_saved_searches") || "[]"),
  savedCandidates: JSON.parse(localStorage.getItem("talentforge_saved_candidates") || "[]"),
  candidateProfiles: JSON.parse(storedCandidateProfiles),
  candidateUploadedFiles: [],
  jobFilters: { title: "", seniority: "", location: "" },
  lastCandidates: new Map(),
  candidateDetails: new Map(),
  conversations: [],
  activeConversationId: null,
  activeMessages: [],
  activeConversationJob: null,
  conversationJobs: JSON.parse(localStorage.getItem("talentforge_conversation_jobs") || "{}"),
  suppressMessageLoad: false,
  messagesUnread: 0,
  cache: {
    dashboard: { data: null, at: 0 },
    jobs: { data: null, at: 0 },
    applications: { data: null, at: 0 },
    recommendations: { data: null, at: 0 },
    messages: { data: null, at: 0 },
    savedCollections: { data: null, at: 0 },
    jobDetails: new Map(),
    jobApplications: new Map(),
    conversations: new Map(),
  },
  pending: new Map(),
};

if (state.recentSearch?.candidates?.length) {
  state.lastCandidates = new Map(
    state.recentSearch.candidates
      .filter((candidate) => candidate?.candidate_id)
      .map((candidate) => [candidate.candidate_id, candidate])
  );
}

const views = {
  landing: document.querySelector("#landing-view"),
  guestUpload: document.querySelector("#guest-upload-view"),
  login: document.querySelector("#auth-view"),
  candidateSetup: document.querySelector("#candidate-setup-view"),
  dashboard: document.querySelector("#dashboard-view"),
};

function $(selector, root = document) {
  return root.querySelector(selector);
}

function $all(selector, root = document) {
  return [...root.querySelectorAll(selector)];
}

function setMessage(text, type = "ok") {
  const message = $(".auth-message");
  if (!message) return;
  message.textContent = text || "";
  message.dataset.type = type;
}

const CACHE_TTL = {
  dashboard: 15000,
  jobs: 20000,
  applications: 20000,
  recommendations: 30000,
  messages: 8000,
  detail: 60000,
};

function nowMs() {
  return Date.now();
}

function isFresh(entry, ttl) {
  return entry?.data && nowMs() - entry.at < ttl;
}

function invalidateCache(...keys) {
  keys.forEach((key) => {
    if (!key) return;
    const entry = state.cache[key];
    if (!entry) return;
    if (entry instanceof Map) entry.clear();
    else {
      entry.data = null;
      entry.at = 0;
    }
  });
}

async function once(key, task) {
  if (state.pending.has(key)) return state.pending.get(key);
  const promise = Promise.resolve()
    .then(task)
    .finally(() => state.pending.delete(key));
  state.pending.set(key, promise);
  return promise;
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new Error(`API'ye ulaşılamadı: ${API_BASE}`);
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiError(data.detail));
  return data;
}

function formatApiError(detail) {
  if (!detail) return "İşlem tamamlanamadı";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .filter(Boolean)
      .join(" / ") || "İşlem tamamlanamadı";
  }
  if (typeof detail === "object") return detail.msg || detail.message || JSON.stringify(detail);
  return String(detail);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setUploadStatus(text, type = "") {
  const status = $("[data-upload-status]");
  if (!status) return;
  status.textContent = text;
  status.dataset.type = type;
}

function setUploadStep(activeStep = null, doneSteps = []) {
  $all("[data-upload-step]").forEach((step) => {
    step.classList.toggle("active", step.dataset.uploadStep === activeStep);
    step.classList.toggle("done", doneSteps.includes(step.dataset.uploadStep));
  });
}

function renderUploadResult(data) {
  const result = $("[data-upload-result]");
  if (!result) return;
  const candidateName = data.candidate_name || data.name || "Aday";
  const skills = (data.skills || []).map((skill) => skill.name || skill).filter(Boolean);
  const experiences = data.experiences || [];
  const educations = data.educations || [];
  const projects = data.projects || [];
  const certifications = data.certifications || [];
  const languages = data.languages || [];
  const companies = [...new Set(experiences.map((exp) => exp.company_name || exp.company).filter(Boolean))];
  const graphNodes = [
    { label: candidateName, type: "Candidate", x: 49, y: 48 },
    ...skills.slice(0, 12).map((label, index) => ({ label, type: "Skill", ...radialPoint(index, 12, 35, 44, 49, 48) })),
    ...experiences.slice(0, 4).map((exp, index) => ({ label: exp.role_title || exp.role || "Experience", type: "Experience", ...radialPoint(index + 1, 5, 25, 76, 49, 48) })),
    ...projects.slice(0, 4).map((project, index) => ({ label: project.name || "Project", type: "Project", ...radialPoint(index + 3, 8, 43, 30, 49, 48) })),
    ...companies.slice(0, 3).map((label, index) => ({ label, type: "Company", ...radialPoint(index + 2, 4, 31, 19, 49, 48) })),
    ...educations.slice(0, 2).map((edu, index) => ({ label: edu.institution || edu.institution_name || edu.degree || "Education", type: "Education", ...radialPoint(index + 3, 6, 30, 72, 49, 48) })),
    ...certifications.slice(0, 2).map((label, index) => ({ label: label.name || label, type: "Certification", ...radialPoint(index + 2, 7, 40, 64, 49, 48) })),
    ...languages.slice(0, 2).map((label, index) => ({ label: label.name || label, type: "Language", ...radialPoint(index + 4, 7, 26, 22, 49, 48) })),
  ].slice(0, 28);
  const relationshipCount =
    skills.length + experiences.length + projects.length + companies.length + educations.length + certifications.length + languages.length;
  const typeCounts = graphNodes.reduce((acc, node) => {
    acc[node.type] = (acc[node.type] || 0) + 1;
    return acc;
  }, {});
  const edges = graphNodes
    .slice(1)
    .map((node, index) => renderGraphEdge(graphNodes[0], node, index))
    .join("");

  result.innerHTML = `
    <div class="neo4j-preview" aria-label="Neo4j bilgi grafı önizleme">
      <div class="neo4j-toolbar">
        <span class="active">Graph</span>
        <span>Table</span>
        <span>RAW</span>
      </div>
      <div class="neo4j-canvas">
        ${edges}
        ${graphNodes
          .map(
            (node, index) => `
              <span
                class="neo-node ${node.type.toLowerCase()}"
                style="left:${node.x}%; top:${node.y}%; animation-delay:${index * 35}ms"
                title="${escapeHtml(node.type)}: ${escapeHtml(node.label)}"
              >
                ${escapeHtml(shortLabel(node.label))}
              </span>`
          )
          .join("")}
      </div>
    </div>
    <div class="neo4j-overview">
      <h3>Results overview</h3>
      <p>Nodes (${graphNodes.length})</p>
      <div class="overview-tags">
        ${Object.entries(typeCounts)
          .map(([type, count]) => `<span class="${type.toLowerCase()}">${escapeHtml(type)} (${count})</span>`)
          .join("")}
      </div>
      <p>Relationships (${relationshipCount})</p>
      <div class="overview-tags rels">
        <span>HAS_SKILL (${skills.length})</span>
        <span>HAS_EXPERIENCE (${experiences.length})</span>
        <span>HAS_PROJECT (${projects.length})</span>
        <span>AT_COMPANY (${companies.length})</span>
        <span>HAS_EDUCATION (${educations.length})</span>
        <span>HAS_CERTIFICATION (${certifications.length})</span>
      </div>
    </div>
    <div class="upload-summary full">
      <strong>${escapeHtml(candidateName)}</strong>
      <span>${escapeHtml(data.summary || "CV yapısal veriye çevrildi ve bilgi grafına kaydedildi.")}</span>
      <div class="pill-list">
        ${skills.slice(0, 8).map((skill) => `<span>${escapeHtml(skill)}</span>`).join("")}
      </div>
      <span>Neo4j kaydı: ${escapeHtml(data.cv_id || "oluşturuldu")}</span>
    </div>
    <div class="guest-profile-detail full">
      <div class="guest-profile-head">
        <div>
          <p class="eyebrow">Çıkarılan aday profili</p>
          <h2>${escapeHtml(candidateName)}</h2>
          <p>${escapeHtml(data.summary || "CV içeriği yapısal profile dönüştürüldü.")}</p>
        </div>
        <span class="graph-state">${data.duplicate ? "Mevcut graf getirildi" : "Yeni graf oluşturuldu"}</span>
      </div>
      <div class="guest-profile-grid">
        <section>
          <h3>Deneyim</h3>
          ${experiences.length ? experiences.map((exp) => `
            <article>
              <strong>${escapeHtml(exp.role_title || exp.role || "Pozisyon")}</strong>
              <span>${escapeHtml(exp.company_name || exp.company || "Şirket belirtilmedi")}</span>
              <small>${escapeHtml([exp.start_date, exp.end_date || (exp.is_current ? "Devam" : "")].filter(Boolean).join(" — "))}</small>
            </article>`).join("") : "<p>Deneyim bilgisi bulunamadı.</p>"}
        </section>
        <section>
          <h3>Eğitim</h3>
          ${educations.length ? educations.map((edu) => `
            <article>
              <strong>${escapeHtml(edu.institution || edu.institution_name || "Kurum")}</strong>
              <span>${escapeHtml([edu.degree, edu.field].filter(Boolean).join(" / "))}</span>
            </article>`).join("") : "<p>Eğitim bilgisi bulunamadı.</p>"}
        </section>
        <section>
          <h3>Projeler</h3>
          ${projects.length ? projects.map((project) => `
            <article>
              <strong>${escapeHtml(project.name || project.title || "Proje")}</strong>
              <span>${escapeHtml(project.description || "")}</span>
            </article>`).join("") : "<p>Proje bilgisi bulunamadı.</p>"}
        </section>
        <section>
          <h3>Dil ve sertifikalar</h3>
          <div class="pill-list">
            ${[...languages, ...certifications].map((item) => `<span>${escapeHtml(item.name || item)}</span>`).join("") || "<span>Bilgi bulunamadı</span>"}
          </div>
        </section>
      </div>
      <section class="guest-skill-section">
        <h3>Yetenekler</h3>
        <div class="pill-list">${skills.map((skill) => `<span>${escapeHtml(skill)}</span>`).join("")}</div>
      </section>
    </div>
  `;
  const complete = $("[data-guest-demo-complete]");
  if (complete) complete.hidden = false;
}

function radialPoint(index, total, radiusX, radiusY, centerX, centerY) {
  const angle = (Math.PI * 2 * index) / total - Math.PI / 2;
  const jitterX = ((index % 3) - 1) * 3;
  const jitterY = ((index % 4) - 1.5) * 2.2;
  return {
    x: Math.max(6, Math.min(88, centerX + Math.cos(angle) * radiusX + jitterX)),
    y: Math.max(8, Math.min(84, centerY + Math.sin(angle) * radiusY + jitterY)),
  };
}

function renderGraphEdge(from, to, index) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  return `
    <span
      class="neo-edge"
      style="left:${from.x}%; top:${from.y}%; width:${length}%; transform:rotate(${angle}deg); animation-delay:${index * 25}ms"
    ></span>
  `;
}

function shortLabel(label) {
  const text = String(label || "");
  return text.length > 13 ? `${text.slice(0, 10)}...` : text;
}

async function uploadLandingCv(file) {
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  const done = [];
  const steps = ["parse", "extract", "graph", "embed"];
  let stepIndex = 0;

  $("[data-upload-result]").innerHTML = "";
  setUploadStatus(`${file.name} işleniyor...`, "");
  setUploadStep(steps[0], []);
  const timer = setInterval(() => {
    if (stepIndex < steps.length - 1) {
      done.push(steps[stepIndex]);
      stepIndex += 1;
      setUploadStep(steps[stepIndex], done);
    }
  }, 1400);

  try {
    const response = await fetch(`${API_BASE}/upload-cv`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(formatApiError(data.detail));
    clearInterval(timer);
    setUploadStep(null, steps);
    setUploadStatus(
      data.duplicate
        ? "Bu CV daha önce işlendi. Mevcut Neo4j bilgi grafı getirildi."
        : "Bilgiler çıkarıldı, Neo4j bilgi grafına kaydedildi ve embedding oluşturuldu.",
      "ok"
    );
    renderUploadResult(data);
  } catch (error) {
    clearInterval(timer);
    setUploadStep(null, done);
    setUploadStatus(error.message, "error");
  }
}

function persistCandidateProfiles() {
  const key = state.user?.id
    ? `talentforge_candidate_profiles:${state.user.id}`
    : "talentforge_candidate_profiles";
  localStorage.setItem(key, JSON.stringify(state.candidateProfiles));
}

function persistConversationJobs() {
  localStorage.setItem("talentforge_conversation_jobs", JSON.stringify(state.conversationJobs));
}

function setCandidateUploadStatus(text, type = "") {
  const targets = [
    $("[data-candidate-upload-status]"),
    $("[data-profile-upload-status]"),
  ].filter(Boolean);
  targets.forEach((status) => {
    status.textContent = text || "";
    status.dataset.type = type;
    status.classList.toggle("is-loading", type === "loading");
  });
}

function extractCandidateProfile(data, fileName) {
  const skills = (data.skills || []).map((skill) => skill.name || skill).filter(Boolean);
  const experiences = data.experiences || [];
  const educations = data.educations || [];
  const projects = data.projects || [];
  const firstExperience = experiences[0] || {};
  const totalYears =
    data.total_experience_years ??
    data.experience_years ??
    estimateExperienceYears(experiences);
  return {
    id: data.cv_id || `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    stage_token: data.stage_token || null,
    file_name: fileName,
    name: data.candidate_name || data.name || state.user?.full_name || "Aday",
    title: firstExperience.role_title || firstExperience.role || data.title || data.profession || "Profil",
    summary: data.summary || "CV işlendi; aday profili bilgi grafına kaydedildi.",
    location: data.location || "-",
    experience_years: totalYears,
    skills,
    educations,
    experiences,
    projects,
    certifications: data.certifications || [],
    languages: data.languages || [],
    cv_id: data.cv_id,
  };
}

function estimateExperienceYears(experiences = []) {
  if (!experiences.length) return "";
  const explicitYears = experiences
    .map((exp) => Number(exp.years_experience || exp.years || 0))
    .filter((year) => year > 0);
  if (explicitYears.length) return Math.round(explicitYears.reduce((sum, year) => sum + year, 0));
  return `${experiences.length} deneyim`;
}

function formatExperienceFact(profile) {
  if (profile.experience_years !== "" && profile.experience_years !== undefined && profile.experience_years !== null) {
    return typeof profile.experience_years === "number"
      ? `${profile.experience_years} yıl deneyim`
      : String(profile.experience_years);
  }
  return (profile.experiences || []).length ? `${profile.experiences.length} deneyim` : "Deneyim bilgisi yok";
}

function renderMiniList(items, formatter, emptyText) {
  const list = (items || []).filter(Boolean);
  if (!list.length) return `<p class="muted-line">${escapeHtml(emptyText)}</p>`;
  return `<div class="mini-list">${list.map((item) => `<p>${formatter(item)}</p>`).join("")}</div>`;
}

function renderProfileSections(profile) {
  return `
    <div class="profile-section-grid">
      <section>
        <h4>Deneyim</h4>
        ${renderMiniList(profile.experiences, (exp) => `
          <strong>${escapeHtml(exp.role_title || exp.role || "Rol")}</strong>
          <span>${escapeHtml(exp.company_name || exp.company || "-")} / ${escapeHtml([exp.start_date, exp.end_date || (exp.is_current ? "Devam" : "")].filter(Boolean).join(" - ") || "-")}</span>
        `, "Deneyim bilgisi bulunamadı.")}
      </section>
      <section>
        <h4>Eğitim</h4>
        ${renderMiniList(profile.educations, (edu) => `
          <strong>${escapeHtml(edu.institution || "Kurum")}</strong>
          <span>${escapeHtml([edu.degree, edu.field, edu.end_year].filter(Boolean).join(" / ") || "-")}</span>
        `, "Eğitim bilgisi bulunamadı.")}
      </section>
      <section>
        <h4>Projeler</h4>
        ${renderMiniList(profile.projects, (project) => `
          <strong>${escapeHtml(project.name || "Proje")}</strong>
          <span>${escapeHtml(project.description || project.role || "-")}</span>
        `, "Proje bilgisi bulunamadı.")}
      </section>
      <section>
        <h4>Dil & sertifika</h4>
        ${renderPills([...(profile.languages || []), ...(profile.certifications || [])])}
      </section>
    </div>
  `;
}

function renderProfileCard(profile, index, { actions = false } = {}) {
  const firstExperience = (profile.experiences || [])[0] || {};
  const experienceSummary = firstExperience.role_title || firstExperience.role
    ? `${firstExperience.role_title || firstExperience.role} / ${firstExperience.company_name || firstExperience.company || "-"}`
    : formatExperienceFact(profile);
  return `
    <article class="extracted-profile-card profile-card-rich">
      <div class="profile-card-head">
        <div>
          <p class="eyebrow">Profil ${index + 1}</p>
          <h3>${escapeHtml(profile.title || "CV profili")}</h3>
          <p>${escapeHtml(experienceSummary)}</p>
        </div>
        ${actions ? `
          <div class="profile-card-actions">
            <button class="ghost-btn" type="button" data-open-cv-profile="${index}">İncele</button>
            <button class="ghost-btn danger" type="button" data-delete-cv-profile="${index}">Sil</button>
          </div>
        ` : ""}
      </div>
      <div class="profile-facts">
        <span>${escapeHtml(formatExperienceFact(profile))}</span>
      </div>
      <section>
        <h4>Yetenekler</h4>
        <div class="pill-list">
          ${(profile.skills || []).slice(0, 10).map((skill) => `<span>${escapeHtml(skill)}</span>`).join("") || "<span>Yetenek bulunamadı</span>"}
        </div>
      </section>
    </article>
  `;
}

function renderCandidateProfilePreview() {
  const preview = $("[data-candidate-profile-preview]");
  const continueButton = $("[data-candidate-setup-continue]");
  if (!preview) return;
  if (!state.candidateProfiles.length) {
    preview.innerHTML = "";
    if (continueButton) continueButton.hidden = true;
    return;
  }
  preview.innerHTML = state.candidateProfiles.map((profile, index) => renderProfileCard(profile, index)).join("");
  if (continueButton) continueButton.hidden = false;
}

function renderUploadedFileList() {
  const root = $("[data-uploaded-file-list]");
  if (!root) return;
  if (!state.candidateUploadedFiles.length) {
    root.innerHTML = "";
    return;
  }
  root.innerHTML = `
    <p>Yüklenenler:</p>
    <div class="uploaded-file-pills">
      ${state.candidateUploadedFiles.map((file, index) => `
        <button type="button" data-open-uploaded-file="${index}">
          ${escapeHtml(file.name)}
        </button>
      `).join("")}
    </div>
  `;
}

function openUploadedFileModal(index) {
  const file = state.candidateUploadedFiles[Number(index)];
  if (!file) return;
  let modal = $(".file-preview-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.className = "file-preview-modal candidate-modal";
    modal.innerHTML = `
      <div class="candidate-modal-backdrop" data-modal-close></div>
      <article class="candidate-modal-card wide" role="dialog" aria-modal="true" aria-label="Yüklenen CV">
        <button class="modal-close" type="button" data-modal-close aria-label="Kapat">×</button>
        <div class="file-preview-body"></div>
      </article>
    `;
    document.body.appendChild(modal);
  }
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  $(".file-preview-body", modal).innerHTML = `
    <div class="modal-head">
      <div>
        <p class="eyebrow">Yüklenen dosya</p>
        <h2>${escapeHtml(file.name)}</h2>
        <p>${isPdf ? "PDF önizlemesi aşağıda gösteriliyor." : "DOCX dosyaları tarayıcı içinde doğrudan render edilemeyebilir; dosyayı yeni sekmede açabilirsin."}</p>
      </div>
      <a class="primary-btn small" href="${file.url}" target="_blank" rel="noreferrer">Dosyayı aç</a>
    </div>
    ${isPdf ? `<iframe class="file-preview-frame" src="${file.url}" title="${escapeHtml(file.name)}"></iframe>` : ""}
  `;
  modal.classList.add("active");
  document.body.classList.add("modal-open");
}

async function commitCandidateProfiles({ stayOnProfile = false } = {}) {
  const tokens = state.candidateProfiles.map((profile) => profile.stage_token).filter(Boolean);
  if (!tokens.length) {
    if (stayOnProfile) {
      renderCandidateProfilesPanel();
      return;
    }
    showView("dashboard");
    setDashboardTab("overview");
    return;
  }
  setCandidateUploadStatus("CV'ler Neo4j bilgi grafına kaydediliyor...", "loading");
  const data = await api("/commit-cvs", {
    method: "POST",
    body: JSON.stringify({ tokens }),
  });
  const committed = data.committed || [];
  state.candidateProfiles = state.candidateProfiles.map((profile) => {
    const match = committed.find((item) => item.stage_token === profile.stage_token);
    return match ? { ...profile, cv_id: match.cv_id, cv_available: match.cv_available, cv_object_name: match.cv_object_name, stage_token: null } : profile;
  });
  persistCandidateProfiles();
  setCandidateUploadStatus(`${committed.length} CV Neo4j bilgi grafına kaydedildi.`, "ok");
  renderCandidateProfilesPanel();
  if (stayOnProfile) {
    setDashboardTab("profile");
    return;
  }
  showView("dashboard");
  setDashboardTab("overview");
}

function getProfileDownloadUrl(profile) {
  if (profile.cv_id) return `${API_BASE}/download-cv/${profile.cv_id}`;
  const localFile = state.candidateUploadedFiles.find((file) => file.name === profile.file_name);
  return localFile?.url || "";
}

function openCvProfileModal(index) {
  const profile = state.candidateProfiles[Number(index)];
  if (!profile) return;
  let modal = $(".cv-profile-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.className = "cv-profile-modal candidate-modal";
    modal.innerHTML = `
      <div class="candidate-modal-backdrop" data-modal-close></div>
      <article class="candidate-modal-card wide" role="dialog" aria-modal="true" aria-label="CV profili">
        <button class="modal-close" type="button" data-modal-close aria-label="Kapat">×</button>
        <div class="cv-profile-modal-body candidate-modal-body"></div>
      </article>
    `;
    document.body.appendChild(modal);
  }
  const downloadUrl = getProfileDownloadUrl(profile);
  $(".cv-profile-modal-body", modal).innerHTML = `
    <div class="modal-head">
      <div>
        <p class="eyebrow">Profil ${Number(index) + 1}</p>
        <h2>${escapeHtml(profile.title || "CV profili")}</h2>
        <p>${escapeHtml(profile.summary || "Özet bulunamadı.")}</p>
      </div>
      ${downloadUrl
        ? `<a class="primary-btn small" href="${downloadUrl}" target="_blank" rel="noreferrer">CV'yi indir</a>`
        : `<button class="ghost-btn" type="button" disabled>CV yok</button>`}
    </div>
    <div class="profile-facts">
      <span>${escapeHtml(profile.file_name || "CV")}</span>
      <span>${escapeHtml(profile.location || "-")}</span>
      <span>${escapeHtml(formatExperienceFact(profile))}</span>
      <span>${escapeHtml((profile.educations || [])[0]?.institution || "Okul bilgisi yok")}</span>
    </div>
    ${renderProfileSections(profile)}
    <section>
      <h3>Yetenekler</h3>
      ${renderPills(profile.skills || [])}
    </section>
  `;
  modal.classList.add("active");
  document.body.classList.add("modal-open");
}

async function deleteCvProfile(index) {
  const profile = state.candidateProfiles[Number(index)];
  if (!profile) return;
  if (profile.cv_id && state.token) {
    await api(`/candidate-cvs/${profile.cv_id}`, { method: "DELETE" });
  }
  state.candidateProfiles.splice(Number(index), 1);
  persistCandidateProfiles();
  renderCandidateProfilesPanel();
  renderProfileHero(state.dashboardSummary || {});
}

function addCandidateCvFromDashboard() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".pdf,.docx";
  input.multiple = true;
  input.addEventListener("change", async () => {
    try {
      await uploadCandidateCvs(input.files);
      await commitCandidateProfiles({ stayOnProfile: true });
    } catch (error) {
      setCandidateUploadStatus(error.message, "error");
    }
  });
  input.click();
}

async function uploadCandidateCvs(files) {
  const list = [...(files || [])].filter(Boolean);
  if (!list.length) return;
  const uploadedProfiles = [];
  setCandidateUploadStatus(`${list.length} CV işleniyor...`, "loading");
  for (let index = 0; index < list.length; index += 1) {
    const file = list[index];
    setCandidateUploadStatus(`[${index + 1}/${list.length}] ${file.name} işleniyor...`, "loading");
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE}/preview-cv`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(formatApiError(data.detail));
    uploadedProfiles.push(extractCandidateProfile(data, file.name));
    state.candidateUploadedFiles.push({
      name: file.name,
      type: file.type,
      url: URL.createObjectURL(file),
    });
    renderUploadedFileList();
  }
  state.candidateProfiles = [...uploadedProfiles, ...state.candidateProfiles].slice(0, 8);
  persistCandidateProfiles();
  renderCandidateProfilePreview();
  setCandidateUploadStatus(`${uploadedProfiles.length} CV işlendi. Devam ettiğinde Neo4j bilgi grafına kaydedilecek.`, "ok");
}

function saveSession(data) {
  const previousUserId = state.user?.id;
  state.token = data.access_token;
  state.user = data.user;
  state.role = data.user?.role || state.role;
  if (previousUserId !== state.user?.id) {
    state.jobs = [];
    state.applications = [];
    state.recommendations = [];
    state.dashboardSummary = null;
    state.conversations = [];
    state.activeConversationId = null;
    state.activeMessages = [];
    state.messagesUnread = 0;
    state.lastCandidates = new Map();
    state.candidateDetails = new Map();
    invalidateCache("dashboard", "jobs", "applications", "recommendations", "messages", "savedCollections");
    state.candidateProfiles = JSON.parse(
      localStorage.getItem(`talentforge_candidate_profiles:${state.user.id}`) || "[]"
    );
  }
  localStorage.setItem("talentforge_token", state.token);
  localStorage.setItem("talentforge_user", JSON.stringify(state.user));
  localStorage.setItem("talentforge_role", state.role);
  syncAuthChrome();
}

function clearSession() {
  state.token = "";
  state.user = null;
  localStorage.removeItem("talentforge_token");
  localStorage.removeItem("talentforge_user");
  localStorage.removeItem("talentforge_role");
  syncAuthChrome();
}

function syncAuthChrome() {
  document.body.classList.toggle("is-authenticated", Boolean(state.token));
}

function showView(name) {
  if (name === "dashboard" && !state.token) name = "login";
  if (name === "candidateSetup" && !state.token) name = "login";
  syncAuthChrome();
  Object.values(views).forEach((view) => view?.classList.remove("active"));
  views[name]?.classList.add("active");
  if (name === "dashboard") {
    setDashboardTab("overview");
    if (state.role === "candidate") {
      renderCandidateOverview(state.dashboardSummary || {});
      renderCandidateProfilesPanel();
      renderCandidateMatchesPanel();
      renderCandidateApplicationsPanel();
    }
    loadDashboard();
  }
  if (name === "candidateSetup") renderCandidateProfilePreview();
  updateLocationHash(name, name === "dashboard" ? "overview" : null);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function updateLocationHash(view = "dashboard", tab = null) {
  if (view === "dashboard") {
    const activeTab = tab || $(".dash-link.active")?.dataset.dashTab || "overview";
    history.replaceState(null, "", `#dashboard/${activeTab}`);
    return;
  }
  history.replaceState(null, "", view === "landing" ? "#home" : `#${view}`);
}

function syncRoleUI() {
  const isCandidate = state.role === "candidate";

  $all("[data-register-role]").forEach((group) => {
    const isActive = group.dataset.registerRole === state.role;
    group.classList.toggle("active", isActive);
    $all("input, select, textarea", group).forEach((field) => {
      field.disabled = !isActive;
    });
  });
  $all(".role-option").forEach((button) => {
    button.classList.toggle("active", button.dataset.role === state.role);
  });
  $all("[data-menu-role]").forEach((menu) => {
    menu.classList.toggle("active", menu.dataset.menuRole === state.role);
  });
  $all("[data-role-dashboard]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.roleDashboard === state.role);
  });

  const roleLabel = $("#dashboard-role-label");
  const title = $("#dashboard-title");
  if (roleLabel) roleLabel.textContent = isCandidate ? "Aday anasayfa" : "İK anasayfa";
  if (title) {
    title.textContent = isCandidate
      ? "Profilini ve başvurularini takip et."
      : "";
  }
}

function setDashboardTab(tab) {
  const activeRoot = $(`[data-role-dashboard="${state.role}"]`);
  if (!activeRoot) return;

  $all(`[data-menu-role="${state.role}"] .dash-link`).forEach((link) => {
    link.classList.toggle("active", link.dataset.dashTab === tab);
  });
  $all(".dashboard-panel", activeRoot).forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === tab);
  });

  const dashTop = $(".dash-top");
  const topButton = $("[data-top-action='search']");
  const isHrSecondaryTab = state.role === "hr" && tab !== "overview";
  const hideHeroForJobs = state.role === "hr" && tab === "jobs";
  dashTop?.classList.toggle("is-hidden", hideHeroForJobs);
  dashTop?.classList.toggle("is-compact", isHrSecondaryTab);
  if (topButton) topButton.hidden = state.role !== "hr" || tab !== "overview";
  updateDashboardHeader(tab);
  if (state.role === "hr" && tab === "overview") renderRecentMatches();
  if (state.role === "hr" && tab === "shortlist") renderSavedCandidatesPanel();
  if (state.role === "candidate" && tab === "matches") {
    renderCandidateMatchesPanel();
    loadCandidateRecommendations()
      .then(() => renderCandidateMatchesPanel())
      .catch((error) => console.warn(error));
  }
  if (state.role === "candidate" && tab === "applications") renderCandidateApplicationsPanel();
  if (tab === "messages" && !state.suppressMessageLoad) loadMessages().catch((error) => console.warn(error));
  updateLocationHash("dashboard", tab);
}

function updateDashboardHeader(tab) {
  const roleLabel = $("#dashboard-role-label");
  const title = $("#dashboard-title");
  const hrLabels = {
    overview: "İK anasayfa",
    search: "Aday arama",
    jobs: "İlanlar",
    shortlist: "Kaydedilen adaylar",
    messages: "Mesajlar",
  };
  const candidateLabels = {
    overview: "Aday anasayfa",
    profile: "Profilim",
    matches: "Eşleşmeler",
    applications: "Ba?vurular",
    messages: "Mesajlar",
  };
  if (roleLabel) {
    roleLabel.textContent = state.role === "hr"
      ? (hrLabels[tab] || "İK anasayfa")
      : (candidateLabels[tab] || "Aday dashboard");
  }
  if (title) {
    title.textContent = state.role === "candidate" && tab === "overview"
      ? "Profilini ve başvurularını takip et."
      : "";
  }
}

function renderMetricGrid(root, metrics) {
  if (!root) return;
  root.innerHTML = metrics
    .map((item) => `<article><span>${item.label}</span><strong>${item.value}</strong></article>`)
    .join("");
}

function renderCompanyCard(summary) {
  const card = $("#hr-dashboard .company-card");
  if (!card || !state.user) return;
  const org = state.user.organization || {};
  const metrics = summary.metrics || {};
  card.innerHTML = `
    <div>
      <p class="eyebrow">Şirket profili</p>
      <h2>${org.name || "İK ekibi"}</h2>
      <p>${metrics.active_jobs ?? summary.total_jobs ?? 0} aktif ilan.</p>
    </div>
  `;
}

function renderHrOverview(summary) {
  const metrics = summary.metrics || {};
  const status = $("#hr-status-summary");
  if (status) {
    const activeJobs = metrics.active_jobs ?? summary.total_jobs ?? 0;
    const applications = metrics.applications ?? summary.total_applications ?? 0;
    const savedSearches = state.savedSearches.length || summary.saved_searches || 0;
    const savedCandidates = state.savedCandidates.length || metrics.shortlist || summary.shortlist || 0;
    status.innerHTML = `
      <p>${activeJobs ? `${activeJobs} aktif ilan yayında.` : "Aktif ilanınız yok."}</p>
      <p>${applications ? `${applications} başvuru takip ediliyor.` : "Henüz başvuru yok."}</p>
      <p>${savedSearches ? `${savedSearches} kayıtlı arama var.` : "Kayıtlı arama yok."}</p>
      <p>${savedCandidates ? `${savedCandidates} aday kaydedildi.` : "Kaydedilen aday yok."}</p>
    `;
  }
  renderRecentMatches();
}

function refreshHrDashboardSummary() {
  if (state.role !== "hr" || !state.dashboardSummary) return;
  const metrics = state.dashboardSummary.metrics || {};
  renderMetricGrid($("#hr-dashboard .metric-grid"), [
    { label: "Aktif ilan", value: metrics.active_jobs ?? state.dashboardSummary.total_jobs ?? 0 },
    { label: "Başvuru", value: metrics.applications ?? state.dashboardSummary.total_applications ?? 0 },
    { label: "Kayıtlı arama", value: state.savedSearches.length || state.dashboardSummary.saved_searches || 0 },
    { label: "Kaydedilen aday", value: state.savedCandidates.length || metrics.shortlist || state.dashboardSummary.shortlist || 0 },
  ]);
  renderHrOverview(state.dashboardSummary);
}

function persistSavedSearches() {
  localStorage.setItem("talentforge_saved_searches", JSON.stringify(state.savedSearches));
}

function persistSavedCandidates() {
  localStorage.setItem("talentforge_saved_candidates", JSON.stringify(state.savedCandidates));
}

function getSavedCandidateReasons(candidate) {
  if (Array.isArray(candidate.reasons) && candidate.reasons.length) return candidate.reasons;
  if (candidate.notes) {
    return String(candidate.notes)
      .split(" / ")
      .map((item) => item.trim())
      .filter((item) => item && !item.toLowerCase().startsWith("pozisyon:"));
  }
  return [];
}

function getSavedCandidatePosition(candidate) {
  if (candidate.search_title || candidate.position || candidate.title) {
    return candidate.search_title || candidate.position || candidate.title;
  }
  const match = String(candidate.notes || "").match(/Pozisyon:\s*([^/]+)/i);
  return match ? match[1].trim() : "Pozisyon belirtilmedi";
}

async function loadSavedCollections({ force = false, preferCache = false } = {}) {
  if (!state.token || state.role !== "hr") return;
  if ((preferCache || !force) && isFresh(state.cache.savedCollections, CACHE_TTL.jobs)) {
    state.savedSearches = state.cache.savedCollections.data.searches || [];
    state.savedCandidates = state.cache.savedCollections.data.candidates || [];
    renderSavedSearches();
    renderSavedCandidatesPanel();
    return;
  }
  try {
    const [searchData, shortlistData] = await once("savedCollections", () => Promise.all([
      api("/saved-searches"),
      api("/shortlists"),
    ]));
    state.savedSearches = searchData.saved_searches || [];
    state.savedCandidates = shortlistData.shortlists || [];
    state.cache.savedCollections = {
      data: { searches: state.savedSearches, candidates: state.savedCandidates },
      at: nowMs(),
    };
    persistSavedSearches();
    persistSavedCandidates();
    renderSavedSearches();
    renderSavedCandidatesPanel();
  } catch (error) {
    console.warn(error);
  }
}

function renderSavedSearches() {
  const list = $("#saved-search-list");
  if (!list) return;
  if (!state.savedSearches.length) {
    list.innerHTML = `
      <div class="empty-state compact">
        <h3>Kayıtlı arama yok</h3>
        <p>Arama yaptıktan sonra "Aramayı kaydet" ile buraya ekleyebilirsin.</p>
      </div>
    `;
    return;
  }
  list.innerHTML = state.savedSearches.map((search) => `
    <article class="saved-item">
      <button type="button" data-run-saved-search="${escapeHtml(search.id)}">
        <strong>${escapeHtml(getSavedSearchTitle(search))}</strong>
        <span>${escapeHtml(search.mode === "text" ? "Metinle arama" : "Kategorik arama")}</span>
      </button>
      <button class="icon-text-btn" type="button" data-delete-saved-search="${escapeHtml(search.id)}">Sil</button>
    </article>
  `).join("");
}

function getSavedSearchTitle(search) {
  const parsed = search.parsed || {};
  const payload = search.payload || {};
  return (
    parsed.title ||
    payload.title ||
    (parsed.must_have_skills || payload.must_have_skills || []).slice(0, 3).join(", ") ||
    search.title ||
    search.name ||
    "Arama"
  );
}

function applySavedSearch(search) {
  renderSearchPanel();
  setDashboardTab("search");
  const mode = search.mode === "text" ? "text" : "categorical";
  setSearchMode(mode);
  const payload = search.payload || {};
  const parsed = search.parsed || {};
  if (mode === "text") {
    const textForm = $("#candidate-text-search-form");
    if (textForm) textForm.query.value = payload.query || search.title || "";
  } else {
    const form = $("#candidate-search-form");
    if (form) {
      form.title.value = payload.title || parsed.title || "";
      form.seniority.value = payload.seniority || parsed.seniority || "";
      form.must_have_skills.value = (payload.must_have_skills || parsed.must_have_skills || []).join(", ");
      form.nice_to_have_skills.value = (payload.nice_to_have_skills || parsed.nice_to_have_skills || []).join(", ");
      form.min_experience_years.value = payload.min_experience_years ?? parsed.min_experience_years ?? 0;
      form.locations.value = (payload.locations || parsed.locations || []).join(", ");
      form.education_institutions.value = (payload.education_institutions || parsed.education_institutions || []).join(", ");
    }
  }
  state.recentSearch = search;
  renderCandidateResults($("#candidate-search-results"), search.candidates || [], search.parsed || null);
}

async function saveCurrentSearch() {
  const recent = state.recentSearch;
  if (!recent) return;
  const title = recent.title || "Yeni arama";
  const item = {
    ...recent,
    id: recent.id || `search-${Date.now()}`,
    title: title.length > 58 ? `${title.slice(0, 55)}...` : title,
  };
  const previousSearches = [...state.savedSearches];
  state.savedSearches = [item, ...state.savedSearches.filter((search) => search.id !== item.id)].slice(0, 12);
  state.cache.savedCollections = {
    data: { searches: state.savedSearches, candidates: state.savedCandidates },
    at: nowMs(),
  };
  persistSavedSearches();
  renderSavedSearches();
  refreshHrDashboardSummary();

  if (state.token) {
    try {
      const data = await api("/saved-searches", {
        method: "POST",
        body: JSON.stringify({
          name: item.title,
          query_spec: {
            mode: item.mode,
            parsed: item.parsed,
            payload: item.payload,
            candidates: item.candidates || [],
          },
        }),
      });
      state.savedSearches = [data.saved_search, ...state.savedSearches.filter((search) => search.id !== item.id)].slice(0, 12);
      state.cache.savedCollections = {
        data: { searches: state.savedSearches, candidates: state.savedCandidates },
        at: nowMs(),
      };
      persistSavedSearches();
      renderSavedSearches();
      refreshHrDashboardSummary();
    } catch (error) {
      state.savedSearches = previousSearches;
      state.cache.savedCollections = {
        data: { searches: state.savedSearches, candidates: state.savedCandidates },
        at: nowMs(),
      };
      persistSavedSearches();
      renderSavedSearches();
      refreshHrDashboardSummary();
      console.warn(error);
    }
  }
}

async function deleteSavedSearch(id) {
  if (state.token) {
    try {
      await api(`/saved-searches/${id}`, { method: "DELETE" });
    } catch (error) {
      console.warn(error);
    }
  }
  state.savedSearches = state.savedSearches.filter((search) => search.id !== id);
  state.cache.savedCollections = {
    data: { searches: state.savedSearches, candidates: state.savedCandidates },
    at: nowMs(),
  };
  persistSavedSearches();
  renderSavedSearches();
  refreshHrDashboardSummary();
}

async function saveCandidate(candidateId) {
  const candidate = state.lastCandidates.get(candidateId);
  if (!candidate) return;
  const currentSearchTitle = state.recentSearch ? getSavedSearchTitle(state.recentSearch) : "";
  let item = {
      candidate_id: candidateId,
      name: candidate.name || "Aday",
      score: candidate.total_score ?? "-",
      reasons: candidate.reasons || [],
      score_breakdown: candidate.score_breakdown || {},
      position: currentSearchTitle || candidate.title || "",
      search_title: currentSearchTitle,
      candidate,
      saved_at: new Date().toISOString(),
    };
  const previousCandidates = [...state.savedCandidates];
  state.savedCandidates = [item, ...state.savedCandidates.filter((saved) => saved.candidate_id !== candidateId)].slice(0, 20);
  state.cache.savedCollections = {
    data: { searches: state.savedSearches, candidates: state.savedCandidates },
    at: nowMs(),
  };
  persistSavedCandidates();
  renderSavedCandidatesPanel();
  refreshHrDashboardSummary();
  const results = $("#candidate-search-results");
  if (results) renderCandidateResults(results, Array.from(state.lastCandidates.values()), state.recentSearch?.parsed || null);

  if (state.token) {
    try {
      const data = await api("/shortlists", {
        method: "POST",
        body: JSON.stringify({
          neo4j_candidate_id: candidateId,
          candidate_name: candidate.name || "Aday",
          score: Number(candidate.total_score || 0),
          notes: [
            currentSearchTitle ? `Pozisyon: ${currentSearchTitle}` : "",
            ...(candidate.reasons || []),
          ].filter(Boolean).join(" / "),
        }),
      });
      item = {
        ...data.shortlist,
        reasons: candidate.reasons || [],
        score_breakdown: candidate.score_breakdown || {},
        position: currentSearchTitle || "",
        search_title: currentSearchTitle || "",
        candidate,
      };
      state.savedCandidates = [item, ...state.savedCandidates.filter((saved) => saved.candidate_id !== candidateId)].slice(0, 20);
      state.cache.savedCollections = {
        data: { searches: state.savedSearches, candidates: state.savedCandidates },
        at: nowMs(),
      };
      persistSavedCandidates();
      renderSavedCandidatesPanel();
      refreshHrDashboardSummary();
      if (results) renderCandidateResults(results, Array.from(state.lastCandidates.values()), state.recentSearch?.parsed || null);
    } catch (error) {
      state.savedCandidates = previousCandidates;
      state.cache.savedCollections = {
        data: { searches: state.savedSearches, candidates: state.savedCandidates },
        at: nowMs(),
      };
      persistSavedCandidates();
      renderSavedCandidatesPanel();
      refreshHrDashboardSummary();
      if (results) renderCandidateResults(results, Array.from(state.lastCandidates.values()), state.recentSearch?.parsed || null);
      console.warn(error);
    }
  }
}

async function deleteSavedCandidate(candidateId) {
  const existing = state.savedCandidates.find((item) => item.candidate_id === candidateId);
  const previous = [...state.savedCandidates];
  state.savedCandidates = state.savedCandidates.filter((item) => item.candidate_id !== candidateId);
  state.cache.savedCollections = {
    data: { searches: state.savedSearches, candidates: state.savedCandidates },
    at: nowMs(),
  };
  persistSavedCandidates();
  renderSavedCandidatesPanel();
  refreshHrDashboardSummary();
  if (state.token && existing?.id) {
    try {
      await api(`/shortlists/${existing.id}`, { method: "DELETE" });
    } catch (error) {
      state.savedCandidates = previous;
      state.cache.savedCollections = {
        data: { searches: state.savedSearches, candidates: state.savedCandidates },
        at: nowMs(),
      };
      persistSavedCandidates();
      renderSavedCandidatesPanel();
      refreshHrDashboardSummary();
      console.warn(error);
    }
  }
}

function renderSavedCandidatesPanel() {
  const panel = $('#hr-dashboard [data-panel="shortlist"]');
  if (!panel) return;
  if (!state.savedCandidates.length) {
    panel.innerHTML = `
      <div class="empty-state">
        <h3>Kaydedilen aday yok</h3>
        <p>Aday arama sonuçlarından "Kaydet" butonuyla adayları buraya alabilirsin.</p>
      </div>
    `;
    return;
  }
  panel.innerHTML = `
    <div class="saved-candidate-grid">
      ${state.savedCandidates.map((candidate) => `
        <article class="saved-candidate-card">
          <div>
            <h3>${escapeHtml(candidate.name)}</h3>
            <p>${escapeHtml(candidate.score)} skor</p>
            <small>${escapeHtml(getSavedCandidatePosition(candidate))}</small>
            <span>${escapeHtml(getSavedCandidateReasons(candidate)[0] || "Açıklama yok")}</span>
          </div>
          <div class="job-actions">
            <button class="ghost-btn" type="button" data-candidate-detail="${escapeHtml(candidate.candidate_id)}">İncele</button>
            <button class="ghost-btn" type="button" data-delete-saved-candidate="${escapeHtml(candidate.candidate_id)}">Kaldır</button>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderRecentMatches() {
  const list = $("#recent-match-list");
  if (!list) return;
  const recent = state.recentSearch;
  const candidates = recent?.candidates || [];
  if (!candidates.length) {
    list.innerHTML = `
      <div class="empty-state compact">
        <h3>Henüz arama yapılmadı</h3>
        <p>Aday arama çalıştırdığında en son sonuçlar burada görünecek.</p>
      </div>
    `;
    return;
  }
  list.innerHTML = candidates.slice(0, 3).map((candidate, index) => `
    <button class="rank-row ${index === 0 ? "hot" : ""}" type="button" data-candidate-detail="${escapeHtml(candidate.candidate_id || "")}">
      <span class="rank">${String(index + 1).padStart(2, "0")}</span>
      <div>
        <strong>${escapeHtml(candidate.name || "Aday")}</strong>
        <p>${escapeHtml(candidate.total_score ?? "-")} skor / ${(candidate.reasons || []).slice(0, 1).map(escapeHtml).join("") || "Açıklama yok"}</p>
      </div>
      <b>${escapeHtml(recent.mode === "text" ? "metinle" : "kategorik")}</b>
    </button>
  `).join("");
}

function renderProfileHero(summary) {
  const hero = $("#candidate-dashboard .profile-hero");
  if (!hero || !state.user) return;
  hero.innerHTML = `
    <div>
      <p class="eyebrow">Aday profili</p>
      <h2>${state.user.full_name || "Aday"}</h2>
      <p>CV profillerini yönet, uygun ilanları takip et ve başvurularını izle.</p>
    </div>
    <span class="status-pill">${state.candidateProfiles.length || 0} CV işlendi</span>
  `;
}

function candidateSkillSet() {
  return new Set(
    (state.candidateProfiles || [])
      .flatMap((profile) => profile.skills || [])
      .map((skill) => String(skill).toLowerCase())
  );
}

function scoreJobForCandidate(job, skills) {
  const required = [...(job.must_have_skills || []), ...(job.nice_to_have_skills || [])];
  if (!required.length || !skills.size) return 0;
  const matched = required.filter((skill) => skills.has(String(skill).toLowerCase())).length;
  return Math.round((matched / required.length) * 100);
}

function calculateProfileCompletion(profile) {
  if (!profile) return 0;
  const checks = [
    profile.name,
    profile.title,
    profile.summary,
    profile.location,
    (profile.skills || []).length >= 3,
    (profile.experiences || []).length,
    (profile.educations || []).length,
    (profile.languages || []).length,
    profile.cv_id,
  ];
  return Math.round((checks.filter(Boolean).length / checks.length) * 100);
}

function renderCandidateOverview(summary = {}) {
  const panel = $('#candidate-dashboard [data-panel="overview"]');
  if (!panel || !state.user) return;
  const profiles = state.candidateProfiles || [];
  const primary = profiles[0] || {};
  const skills = candidateSkillSet();
  const applications = state.applications || [];
  const recommended = (state.recommendations || []).slice(0, 4);
  const completion = calculateProfileCompletion(primary);
  const skillNames = [...skills].slice(0, 8).map((skill) => skill.replace(/\b\w/g, (char) => char.toUpperCase()));
  const signals = [
    skillNames.length ? `${skillNames.slice(0, 4).join(", ")} becerileri profilde öne çıkıyor.` : "CV yüklendiğinde yetenek sinyalleri burada oluşacak.",
    primary.experiences?.length ? `${primary.experiences.length} deneyim kaydı bilgi grafına işlendi.` : "Deneyim bilgisi tamamlanmayı bekliyor.",
    primary.educations?.length ? `${primary.educations.length} eğitim kaydı çıkarıldı.` : "Eğitim bilgisi bulunamadı.",
  ];

  panel.innerHTML = `
    <div class="profile-hero">
      <div>
        <p class="eyebrow">Aday profili</p>
        <h2>${escapeHtml(state.user.full_name || primary.name || "Aday")}</h2>
        <p>${escapeHtml([
          primary.title,
          primary.location,
          formatExperienceFact(primary),
        ].filter(Boolean).join(" / ") || "CV profillerini yönet, uygun ilanları takip et ve başvurularını izle.")}</p>
      </div>
      <span class="status-pill">${profiles.length || 0} CV işlendi</span>
    </div>
    <div class="metric-grid">
      <article><span>Uygun ilan</span><strong>${state.recommendations.length}</strong></article>
      <article><span>Başvuru</span><strong>${applications.length}</strong></article>
      <article><span>Profil doluluk</span><strong>${completion}%</strong></article>
      <article><span>Mesaj</span><strong>${state.messagesUnread || 0}</strong></article>
    </div>
    <div class="dash-panels">
      <section class="dash-panel">
        <h2>Profil sinyalleri</h2>
        ${signals.map((signal) => `<p>${escapeHtml(signal)}</p>`).join("")}
        <div class="progress"><span style="width:${completion}%"></span></div>
      </section>
      <section class="dash-panel">
        <h2>Önerilen pozisyonlar</h2>
        ${
          recommended.length
            ? recommended.map((job, index) => `
              <button class="rank-row ${index === 0 ? "hot" : ""}" type="button" data-job-detail="${escapeHtml(job.job?.id || job.id)}">
                <span class="rank">${String(index + 1).padStart(2, "0")}</span>
                <div>
                  <strong>${escapeHtml(job.job?.title || job.title)}</strong>
                  <p>${escapeHtml(job.match_score ? `${job.match_score} uyum skoru` : "Yeni ilan")}</p>
                </div>
                <b>${job.job?.application ? "Başvuruldu" : "İncele"}</b>
              </button>
            `).join("")
            : `<div class="empty-state compact"><h3>Henüz öneri yok</h3><p>İlan yayınlandığında profilinle karşılaştırılacak.</p></div>`
        }
      </section>
    </div>
  `;
}

function renderCandidateProfilesPanel() {
  const panel = $('#candidate-dashboard [data-panel="profile"]');
  if (!panel) return;
  const profiles = state.candidateProfiles || [];
  if (!profiles.length) {
    panel.innerHTML = `
      <div class="empty-state">
        <h3>Henüz CV profili yok</h3>
        <p>CV yüklediğinde çıkarılan profil bilgileri burada görünecek.</p>
        <button class="primary-btn small" type="button" data-add-candidate-cv>CV yükle</button>
        <p class="candidate-upload-status" data-profile-upload-status></p>
      </div>
    `;
    return;
  }
  panel.innerHTML = `
    <div class="candidate-profile-preview in-dashboard">
      ${profiles.map((profile, index) => renderProfileCard(profile, index, { actions: true })).join("")}
    </div>
    <section class="add-cv-panel">
      <div>
        <p class="eyebrow">Yeni CV</p>
        <h3>Başka bir rol için yeni profil oluştur</h3>
        <p>AI Developer, Cloud Engineer veya farklı ilanlar için hazırladığın ayrı CV'leri ekleyebilirsin.</p>
      </div>
      <button class="primary-btn small" type="button" data-add-candidate-cv>Yeni CV ekle</button>
    </section>
    <p class="candidate-upload-status" data-profile-upload-status></p>
  `;
}

async function loadDashboard() {
  syncRoleUI();
  try {
    const summary = await getDashboardSummary();
    state.dashboardSummary = summary;
    const metrics = summary.metrics || {};
    if (state.role === "hr") {
      await loadSavedCollections({ preferCache: true });
      renderCompanyCard(summary);
      renderMetricGrid($("#hr-dashboard .metric-grid"), [
        { label: "Aktif ilan", value: metrics.active_jobs ?? summary.total_jobs ?? 0 },
        { label: "Başvuru", value: metrics.applications ?? summary.total_applications ?? 0 },
        { label: "Kayıtlı arama", value: state.savedSearches.length || summary.saved_searches || 0 },
        { label: "Kaydedilen aday", value: state.savedCandidates.length || metrics.shortlist || summary.shortlist || 0 },
      ]);
      renderHrOverview(summary);
      await loadJobs({ preferCache: true });
      loadMessages({ preferCache: true }).catch((error) => console.warn(error));
    } else {
      renderCandidateOverview(summary);
      renderCandidateProfilesPanel();
      const jobsTask = loadJobs({ preferCache: true });
      const applicationsTask = loadApplications({ preferCache: true }).then(() => {
        renderCandidateOverview(summary);
        renderCandidateApplicationsPanel();
      });
      const recommendationsTask = loadCandidateRecommendations({ preferCache: true }).then(() => {
        renderCandidateOverview(summary);
        renderCandidateMatchesPanel();
      });
      await Promise.allSettled([jobsTask, applicationsTask, recommendationsTask]);
      loadMessages({ preferCache: true }).catch((error) => console.warn(error));
    }
  } catch (error) {
    console.warn(error);
  }
}

async function getDashboardSummary({ force = false } = {}) {
  if (!force && isFresh(state.cache.dashboard, CACHE_TTL.dashboard)) {
    state.dashboardSummary = state.cache.dashboard.data;
    return state.cache.dashboard.data;
  }
  return once("dashboard", async () => {
    const summary = await api("/dashboard");
    state.cache.dashboard = { data: summary, at: nowMs() };
    state.dashboardSummary = summary;
    return summary;
  });
}

async function loadJobs({ force = false, preferCache = false } = {}) {
  if ((preferCache || !force) && isFresh(state.cache.jobs, CACHE_TTL.jobs)) {
    state.jobs = state.cache.jobs.data;
    renderJobs();
    return state.jobs;
  }
  try {
    const data = await once("jobs", () => api("/jobs?limit=100&offset=0"));
    state.jobs = data.jobs || [];
    state.cache.jobs = { data: state.jobs, at: nowMs() };
    renderJobs();
    return state.jobs;
  } catch (error) {
    console.warn(error);
    state.jobs = [];
    renderJobs();
    return state.jobs;
  }
}

function renderJobs() {
  const panel = $('#hr-dashboard [data-panel="jobs"]');
  if (!panel) return;
  {
  const filters = state.jobFilters;
  const titleOptions = [...new Set(state.jobs.map((job) => job.title).filter(Boolean))];
  const seniorityOptions = [...new Set(state.jobs.map((job) => job.seniority).filter(Boolean))];
  const locationOptions = [...new Set(state.jobs.map((job) => job.location).filter(Boolean))];
  const filteredJobs = state.jobs.filter((job) => {
    const titleOk = !filters.title || job.title === filters.title;
    const seniorityOk = !filters.seniority || job.seniority === filters.seniority;
    const locationOk = !filters.location || job.location === filters.location;
    return titleOk && seniorityOk && locationOk;
  });
  const jobsMarkup = filteredJobs.length
    ? filteredJobs.map((job) => `
      <article class="job-card">
        <button class="job-card-main" type="button" data-job-detail="${escapeHtml(job.id)}">
          <strong>${escapeHtml(job.title)}</strong>
          <span>${escapeHtml(job.location || "-")} / ${escapeHtml(job.seniority || "Kıdem farketmez")} / ${escapeHtml(job.status || "published")}</span>
          <small>${escapeHtml((job.must_have_skills || []).join(", ") || "Zorunlu yetenek girilmedi")}</small>
        </button>
        <div class="job-actions">
          <button class="ghost-btn" type="button" data-job-applications="${escapeHtml(job.id)}">${job.application_count || 0} başvuru</button>
          <button class="ghost-btn" type="button" data-job-detail="${escapeHtml(job.id)}">Detay</button>
          <button class="ghost-btn danger" type="button" data-delete-job="${escapeHtml(job.id)}">Sil</button>
        </div>
      </article>
    `).join("")
    : `
      <div class="empty-state">
        <h3>${state.jobs.length ? "Filtreye uygun ilan yok" : "Aktif ilanınız yok"}</h3>
        <p>${state.jobs.length ? "Filtreleri temizleyip tekrar deneyebilirsin." : "İlk ilanı oluşturduğunda aday eşleştirme ve başvuru akışı bu sayfadan takip edilecek."}</p>
        <button class="primary-btn small" type="button" data-job-action="new">Yeni ilan</button>
      </div>
    `;

  panel.innerHTML = `
    <div class="dash-panels ${state.jobs.length ? "" : "jobs-empty"}">
      <section class="dash-panel job-template" id="job-template-panel">
        <div class="panel-heading">
          <h2>Yeni ilan taslağı</h2>
          ${state.jobs.length ? `<button class="ghost-btn" type="button" data-job-action="close">Kapat</button>` : ""}
        </div>
        <form class="stack-form" id="job-form">
          <label>Pozisyon<input name="title" required placeholder="Senior Backend Engineer" /></label>
          <label>Açıklama<textarea name="description" rows="5" required placeholder="Rolün sorumlulukları, ekip yapısı ve aranan temel nitelikler..."></textarea></label>
          <label>Lokasyon<input name="location" placeholder="Istanbul / Remote" /></label>
          <label>Kıdem
            <select name="seniority">
              <option value="">Farketmez</option>
              <option value="junior">Junior</option>
              <option value="mid">Mid</option>
              <option value="senior">Senior</option>
              <option value="lead">Lead</option>
            </select>
          </label>
          <label>Min. deneyim<input name="min_experience_years" type="number" min="0" max="50" value="0" /></label>
          <label>Zorunlu yetenekler<input name="must_have_skills" placeholder="Python, FastAPI, AWS" /></label>
          <label>Tercih edilenler<input name="nice_to_have_skills" placeholder="Docker, Kubernetes, Redis" /></label>
          <button class="primary-btn full" type="submit">İlanı yayınla</button>
          <p class="panel-message"></p>
        </form>
      </section>
      <section class="dash-panel">
        <div class="panel-heading">
          <h2>İlanlar</h2>
          <button class="primary-btn small" type="button" data-job-action="new">Yeni ilan</button>
        </div>
        <div class="job-filters">
          <label>Pozisyon
            <select data-job-filter="title">
              <option value="">Tümü</option>
              ${titleOptions.map((title) => `<option value="${escapeHtml(title)}" ${filters.title === title ? "selected" : ""}>${escapeHtml(title)}</option>`).join("")}
            </select>
          </label>
          <label>Kıdem
            <select data-job-filter="seniority">
              <option value="">Tümü</option>
              ${seniorityOptions.map((seniority) => `<option value="${escapeHtml(seniority)}" ${filters.seniority === seniority ? "selected" : ""}>${escapeHtml(seniority)}</option>`).join("")}
            </select>
          </label>
          <label>Konum
            <select data-job-filter="location">
              <option value="">Tümü</option>
              ${locationOptions.map((location) => `<option value="${escapeHtml(location)}" ${filters.location === location ? "selected" : ""}>${escapeHtml(location)}</option>`).join("")}
            </select>
          </label>
        </div>
        <div id="hr-job-list" class="job-grid">${jobsMarkup}</div>
      </section>
    </div>
  `;
  $("#job-form")?.addEventListener("submit", createJob);
  $all("[data-job-filter]", panel).forEach((field) => {
    field.addEventListener("change", () => {
      state.jobFilters[field.dataset.jobFilter] = field.value;
      renderJobs();
    });
  });
  $all("[data-job-action='new']", panel).forEach((button) => {
    button.addEventListener("click", () => $("#job-template-panel")?.classList.add("active"));
  });
  $("[data-job-action='close']", panel)?.addEventListener("click", () => {
    $("#job-template-panel")?.classList.remove("active");
  });
  return;
  }
  const jobsMarkup = state.jobs.length
    ? state.jobs
        .map(
          (job) => `
            <p>
              <strong>${job.title}</strong><br>
              ${job.location || "-"} / ${job.status || "published"}<br>
              <small>${(job.must_have_skills || []).join(", ") || "Zorunlu yetenek girilmedi"}</small>
            </p>`
        )
        .join("")
    : `
        <div class="empty-state">
          <h3>Aktif ilanınız yok</h3>
          <p>İlk ilanı oluşturduğunda aday eşleştirme ve başvuru akışı bu sayfadan takip edilecek.</p>
          <button class="primary-btn small" type="button" data-job-action="new">Yeni ilan</button>
        </div>
      `;

  panel.innerHTML = `
    <div class="dash-panels ${state.jobs.length ? "" : "jobs-empty"}">
      <section class="dash-panel job-template" id="job-template-panel">
        <div class="panel-heading">
          <h2>Yeni ilan taslagi</h2>
          ${state.jobs.length ? `<button class="ghost-btn" type="button" data-job-action="close">Kapat</button>` : ""}
        </div>
        <form class="stack-form" id="job-form">
          <label>Pozisyon<input name="title" required placeholder="Senior Backend Engineer" /></label>
          <label>Açıklama<textarea name="description" rows="5" required placeholder="Rolün sorumlulukları, ekip yapısı ve aranan temel nitelikler..."></textarea></label>
          <label>Lokasyon<input name="location" placeholder="Istanbul / Remote" /></label>
          <label>Kıdem
            <select name="seniority">
              <option value="">Farketmez</option>
              <option value="junior">Junior</option>
              <option value="mid">Mid</option>
              <option value="senior">Senior</option>
              <option value="lead">Lead</option>
            </select>
          </label>
          <label>Min. deneyim<input name="min_experience_years" type="number" min="0" max="50" value="0" /></label>
          <label>Zorunlu yetenekler<input name="must_have_skills" placeholder="Python, FastAPI, AWS" /></label>
          <label>Tercih edilenler<input name="nice_to_have_skills" placeholder="Docker, Kubernetes, Redis" /></label>
          <button class="primary-btn full" type="submit">İlani yayınla</button>
          <p class="panel-message"></p>
        </form>
      </section>
      <section class="dash-panel">
        <div class="panel-heading">
          <h2>İlanlar</h2>
          ${state.jobs.length ? `<button class="primary-btn small" type="button" data-job-action="new">Yeni ilan</button>` : ""}
        </div>
        <div id="hr-job-list" class="list-stack">
          ${jobsMarkup}
        </div>
      </section>
    </div>
  `;
  $("#job-form")?.addEventListener("submit", createJob);
  $all("[data-job-action='new']", panel).forEach((button) => {
    button.addEventListener("click", () => $("#job-template-panel")?.classList.add("active"));
  });
  $("[data-job-action='close']", panel)?.addEventListener("click", () => {
    $("#job-template-panel")?.classList.remove("active");
  });
}

async function createJob(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (form.dataset.loading === "true") return;
  const message = $(".panel-message", form);
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.must_have_skills = (payload.must_have_skills || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  payload.nice_to_have_skills = (payload.nice_to_have_skills || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  payload.min_experience_years = Number(payload.min_experience_years || 0);
  payload.status = "published";

  try {
    setFormLoading(form, true, "Yayınlanıyor...");
    const data = await api("/jobs", { method: "POST", body: JSON.stringify(payload) });
    const createdJob = data.job;
    if (createdJob) {
      state.jobs = [createdJob, ...state.jobs.filter((job) => job.id !== createdJob.id)];
      state.cache.jobs = { data: state.jobs, at: nowMs() };
      if (state.dashboardSummary?.metrics) {
        state.dashboardSummary.metrics.active_jobs = (state.dashboardSummary.metrics.active_jobs || 0) + 1;
        state.cache.dashboard = { data: state.dashboardSummary, at: nowMs() };
      }
    }
    if (message) {
      message.textContent = "İlan oluşturuldu.";
      message.dataset.type = "ok";
    }
    form.reset();
    refreshHrDashboardSummary();
    renderJobs();
    setDashboardTab("jobs");
  } catch (error) {
    if (message) {
      message.textContent = error.message;
      message.dataset.type = "error";
    }
  } finally {
    setFormLoading(form, false);
  }
}

function renderCandidateResults(results, candidates, parsed = null) {
  if (!results) return;
  const list = candidates || [];
  state.lastCandidates = new Map(list.map((candidate) => [candidate.candidate_id, candidate]));
  state.recentSearch = {
    id: `search-${Date.now()}`,
    mode: parsed ? "text" : "categorical",
    parsed,
    payload: parsed,
    title: parsed
      ? parsed.title || (parsed.must_have_skills || []).join(", ") || "Metinle arama"
      : "Kategorik arama",
    candidates: list,
    created_at: new Date().toISOString(),
  };
  localStorage.setItem("talentforge_recent_search", JSON.stringify(state.recentSearch));
  renderRecentMatches();
  const parsedMarkup = parsed
    ? `
      <div class="query-spec">
        <span>Pozisyon: ${escapeHtml(parsed.title || "-")}</span>
        <span>Kıdem: ${escapeHtml(parsed.seniority || "-")}</span>
        <span>Zorunlu: ${escapeHtml((parsed.must_have_skills || []).join(", ") || "-")}</span>
        <span>Tercih: ${escapeHtml((parsed.nice_to_have_skills || []).join(", ") || "-")}</span>
        <span>Eğitim: ${escapeHtml((parsed.education_institutions || []).join(", ") || parsed.education_level || "-")}</span>
      </div>
    `
    : "";

  results.innerHTML = `
    ${parsedMarkup}
    <div class="search-result-actions">
      <button class="ghost-btn" type="button" data-save-current-search>Aramayı kaydet</button>
    </div>
    <div class="table-row head"><span>Aday</span><span>Skor</span><span>Açıklama</span><span>Aksiyon</span></div>
    ${
      list.length
        ? list
            .map((candidate) => {
              const saved = state.savedCandidates.some((item) => item.candidate_id === candidate.candidate_id);
              return `
                <div class="table-row">
                  <span>${escapeHtml(candidate.name || "-")}</span>
                  <span>${escapeHtml(candidate.total_score ?? "-")}</span>
                  <span>${escapeHtml((candidate.reasons || []).join(" / ") || "Açıklama yok")}</span>
                  <span class="row-actions">
                    <button type="button" data-candidate-detail="${escapeHtml(candidate.candidate_id || "")}">İncele</button>
                    <button type="button" data-save-candidate="${escapeHtml(candidate.candidate_id || "")}">${saved ? "Kaydedildi" : "Kaydet"}</button>
                  </span>
                </div>`;
            })
            .join("")
        : `<div class="table-row"><span>Uygun aday bulunamadı</span><span>-</span><span>-</span><span>-</span></div>`
    }
  `;
}
async function searchCandidates(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (form.dataset.loading === "true") return;
  const message = $(".panel-message", form);
  const results = $("#candidate-search-results");
  const raw = Object.fromEntries(new FormData(form).entries());
  const payload = {
    title: raw.title || null,
    seniority: raw.seniority || null,
    must_have_skills: splitList(raw.must_have_skills),
    nice_to_have_skills: splitList(raw.nice_to_have_skills),
    min_experience_years: Number(raw.min_experience_years || 0),
    preferred_industries: [],
    locations: splitList(raw.locations),
    languages: [],
    education_level: null,
    education_institutions: splitList(raw.education_institutions),
    must_have_certifications: [],
    free_text: null,
  };

  try {
    setFormLoading(form, true);
    const data = await api("/search-candidates", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (message) message.textContent = `${data.length} aday bulundu.`;
    renderCandidateResults(results, data);
    if (state.recentSearch) {
      state.recentSearch.payload = payload;
      localStorage.setItem("talentforge_recent_search", JSON.stringify(state.recentSearch));
    }
  } catch (error) {
    if (message) {
      message.textContent = error.message;
      message.dataset.type = "error";
    }
  } finally {
    setFormLoading(form, false);
  }
}

async function searchCandidatesText(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (form.dataset.loading === "true") return;
  const message = $(".panel-message", form);
  const results = $("#candidate-search-results");
  const query = new FormData(form).get("query")?.toString().trim();
  if (!query) {
    if (message) {
      message.textContent = "Arama metni bos olamaz.";
      message.dataset.type = "error";
    }
    return;
  }

  try {
    setFormLoading(form, true);
    const data = await api("/nl-search", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    const candidates = data.results || [];
    const parsed = data.parsed_query || {};
    if (message) {
      message.textContent = `${candidates.length} aday bulundu. Sistem sorguyu yapısal kriterlere çevirdi.`;
      message.dataset.type = "ok";
    }
    if (results) {
      renderCandidateResults(results, candidates, parsed);
      if (state.recentSearch) {
        state.recentSearch.payload = { query };
        localStorage.setItem("talentforge_recent_search", JSON.stringify(state.recentSearch));
      }
    }
  } catch (error) {
    if (message) {
      message.textContent = error.message;
      message.dataset.type = "error";
    }
  } finally {
    setFormLoading(form, false);
  }
}

function renderSearchPanel() {
  const panel = $('#hr-dashboard [data-panel="search"]');
  if (!panel) return;
  panel.innerHTML = `
    <div class="dash-panels wide-left">
      <section class="dash-panel">
        <div class="panel-heading">
          <h2>Aday arama</h2>
        </div>
        <div class="segmented-control" role="tablist" aria-label="Arama modu">
          <button class="active" type="button" data-search-mode-button="categorical">Kategorik arama</button>
          <button type="button" data-search-mode-button="text">Metinle arama</button>
        </div>
        <div class="search-mode active" data-search-mode="categorical">
          <form class="stack-form" id="candidate-search-form">
            <label>Pozisyon<input name="title" placeholder="Backend Developer" /></label>
            <label>Kıdem
              <select name="seniority">
                <option value="">Farketmez</option>
                <option value="junior">Junior</option>
                <option value="mid">Mid</option>
                <option value="senior">Senior</option>
                <option value="lead">Lead</option>
              </select>
            </label>
            <label>Zorunlu yetenekler<input name="must_have_skills" placeholder="Python, FastAPI, AWS" /></label>
            <label>Tercih edilenler<input name="nice_to_have_skills" placeholder="Docker, Kubernetes" /></label>
            <label>Min. deneyim<input name="min_experience_years" type="number" min="0" value="0" /></label>
            <label>Lokasyon<input name="locations" placeholder="Istanbul, Remote" /></label>
            <label>Eğitim kurumu<input name="education_institutions" placeholder="ODTÜ, Marmara Üniversitesi" /></label>
            <button class="primary-btn full" type="submit">Aday ara</button>
            <p class="panel-message"></p>
          </form>
        </div>
        <div class="search-mode" data-search-mode="text">
          <form class="stack-form" id="candidate-text-search-form">
            <label>Arama metni
              <textarea name="query" rows="8" placeholder="Fintech alanında çalışmış senior backend geliştirici arıyoruz. Python, FastAPI, PostgreSQL ve Redis zorunlu olsun. AWS ve Kubernetes bilmesi iyi olur."></textarea>
            </label>
            <button class="primary-btn full" type="submit">Metinle aday ara</button>
            <p class="panel-message"></p>
          </form>
        </div>
      </section>
      <section class="dash-panel">
        <h2>Kayıtlı aramalar</h2>
        <div id="saved-search-list" class="saved-list"></div>
      </section>
    </div>
    <div class="candidate-table" id="candidate-search-results">
      <div class="table-row head"><span>Aday</span><span>Skor</span><span>Açıklama</span><span>Aksiyon</span></div>
    </div>
  `;
  $("#candidate-search-form")?.addEventListener("submit", searchCandidates);
  $("#candidate-text-search-form")?.addEventListener("submit", searchCandidatesText);
  renderSavedSearches();
  setSearchMode("categorical");
}

async function loadApplications() {
  if (isFresh(state.cache.applications, CACHE_TTL.applications)) {
    state.applications = state.cache.applications.data;
    return state.applications;
  }
  try {
    const data = await once("applications", () => api("/applications/me?limit=50&offset=0"));
    state.applications = data.applications || [];
    state.cache.applications = { data: state.applications, at: nowMs() };
    return state.applications;
  } catch (error) {
    console.warn(error);
    return state.applications;
  }
}

function renderCandidateApplicationsPanel() {
  const panel = $('#candidate-dashboard [data-panel="applications"]');
  if (!panel) return;
  const applications = state.applications || [];
  panel.innerHTML = `
    <div class="dash-panel">
      <div class="panel-title-row">
        <h2>Başvurularım</h2>
        <span class="status-pill">${applications.length} başvuru</span>
      </div>
      <div class="timeline application-timeline">
        ${
          applications.length
            ? applications.map((application) => {
                const job = application.job || {};
                const reasons = application.match_breakdown?.reasons || [];
                return `
                  <article>
                    <span>${escapeHtml(application.status || "submitted")}</span>
                    <h3>${escapeHtml(job.title || "İlan")}</h3>
                    <p>${escapeHtml([job.organization, job.location].filter(Boolean).join(" / ") || "İlan bilgisi")}</p>
                    <p>${escapeHtml(application.match_score ? `${application.match_score} uyum skoru` : "Skor hesaplanıyor")}</p>
                    ${reasons.length ? `<p>${escapeHtml(reasons.slice(0, 2).join(" / "))}</p>` : ""}
                    <button class="ghost-btn small" type="button" data-job-detail="${escapeHtml(job.id || "")}" ${job.id ? "" : "disabled"}>İlanı incele</button>
                  </article>`;
              }).join("")
            : `<div class="empty-state compact"><h3>Henüz başvuru yok</h3><p>Uygun ilanlardan başvuru yaptığında burada görünecek.</p></div>`
        }
      </div>
    </div>
  `;
}

function applicationExperienceLabel(application) {
  const reasons = application.match_breakdown?.reasons || [];
  const experienceReason = reasons.find((reason) => /Deneyim:\s*\d+/i.test(reason));
  const parsed = experienceReason?.match(/Deneyim:\s*(\d+)/i)?.[1];
  if (parsed) return `${parsed} yıl`;
  const years = application.candidate?.experience_years;
  return years !== undefined && years !== null && Number(years) > 0 ? `${years} yıl` : "";
}

async function loadCandidateRecommendations({ force = false, preferCache = false } = {}) {
  if ((preferCache || !force) && isFresh(state.cache.recommendations, CACHE_TTL.recommendations)) {
    state.recommendations = state.cache.recommendations.data;
    return state.recommendations;
  }
  try {
    const data = await once("recommendations", () => api("/candidate/recommendations?limit=25"));
    state.recommendations = data.recommendations || [];
    state.recommendationsLoadedAt = nowMs();
    state.cache.recommendations = { data: state.recommendations, at: nowMs() };
    return state.recommendations;
  } catch (error) {
    console.warn(error);
    state.recommendations = [];
    return state.recommendations;
  }
}

function renderCandidateMatchesPanel() {
  const panel = $('#candidate-dashboard [data-panel="matches"]');
  if (!panel) return;
  const rows = state.recommendations || [];
  panel.innerHTML = `
    <div class="dash-card">
      <div class="panel-heading">
        <h2>Önerilen ilanlar</h2>
        <span class="status-pill">${rows.length} eşleşme</span>
      </div>
      <div class="candidate-table">
        <div class="table-row head"><span>Pozisyon</span><span>Skor</span><span>Neden?</span><span>Aksiyon</span></div>
        ${
          rows.length
            ? rows.map((item) => {
                const job = item.job || {};
                const reasons = item.reasons || [];
                return `
                  <div class="table-row">
                    <span>${escapeHtml(job.title || "-")}</span>
                    <span>${escapeHtml(item.match_score ?? "-")}</span>
                    <span>${escapeHtml(reasons.join(" / ") || "Matcher skoru ile önerildi.")}</span>
                    <span class="row-actions">
                      <button type="button" data-job-detail="${escapeHtml(job.id || "")}">İncele</button>
                      ${job.application ? `<button type="button" disabled>Başvuruldu</button>` : `<button type="button" data-apply-job="${escapeHtml(job.id || "")}">Başvur</button>`}
                    </span>
                  </div>`;
              }).join("")
            : `<div class="table-row"><span>Henüz uygun ilan yok</span><span>-</span><span>CV profilin matcher ile ilanlara göre skorlanacak.</span><span>-</span></div>`
        }
      </div>
    </div>
  `;
}

async function applyToJob(jobId) {
  if (!jobId) return;
  const job = state.jobs.find((item) => item.id === jobId) || {};
  state.recommendations = state.recommendations.map((item) =>
    item.job?.id === jobId ? { ...item, job: { ...item.job, application: { status: "submitted" } } } : item
  );
  renderCandidateMatchesPanel();
  const data = await api(`/jobs/${jobId}/apply`, {
    method: "POST",
    body: JSON.stringify({ cover_letter: "" }),
  });
  if (data.application) {
    state.applications = [data.application, ...state.applications.filter((item) => item.id !== data.application.id)];
    state.cache.applications = { data: state.applications, at: nowMs() };
    state.recommendations = state.recommendations.map((item) =>
      item.job?.id === jobId ? { ...item, job: { ...(item.job || job), application: data.application } } : item
    );
    state.cache.recommendations = { data: state.recommendations, at: nowMs() };
  }
  renderCandidateOverview(state.dashboardSummary || {});
  renderCandidateMatchesPanel();
  renderCandidateApplicationsPanel();
}

function splitList(value) {
  return (value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function setFormLoading(form, isLoading, label = "Aranıyor...") {
  const button = $("button[type='submit']", form);
  if (!button) return;
  if (isLoading) {
    button.dataset.originalText = button.textContent;
    button.textContent = label;
    button.disabled = true;
    form.dataset.loading = "true";
    form.classList.add("is-loading");
    return;
  }
  button.textContent = button.dataset.originalText || button.textContent;
  button.disabled = false;
  form.dataset.loading = "false";
  form.classList.remove("is-loading");
}

function formatBreakdown(breakdown = {}) {
  const entries = Object.entries(breakdown);
  if (!entries.length) return `<p class="muted-line">Skor kırılımı yok.</p>`;
  return entries
    .map(([name, value]) => `<article><span>${name.replaceAll("_", " ")}</span><strong>${value}</strong></article>`)
    .join("");
}

function renderPills(items = [], key = null) {
  const values = items
    .map((item) => (key && item ? item[key] : item))
    .filter(Boolean)
    .slice(0, 18);
  if (!values.length) return `<p class="muted-line">Kayıt yok.</p>`;
  return `<div class="pill-list">${values.map((value) => `<span>${value}</span>`).join("")}</div>`;
}

function renderTimeline(items = []) {
  if (!items.length) return `<p class="muted-line">Deneyim kaydı yok.</p>`;
  return items
    .slice(0, 4)
    .map(
      (item) => `
        <article class="modal-timeline-item">
          <strong>${item.role || "Rol belirtilmedi"}</strong>
          <span>${item.company || "Şirket belirtilmedi"} / ${item.start_date || "-"} - ${item.end_date || (item.is_current ? "Devam" : "-")}</span>
          <p>${item.description || ""}</p>
        </article>`
    )
    .join("");
}

function renderProjects(items = []) {
  if (!items.length) return `<p class="muted-line">Proje kaydı yok.</p>`;
  return items
    .slice(0, 4)
    .map(
      (item) => `
        <article class="modal-timeline-item">
          <strong>${item.name || "Proje"}</strong>
          <span>${item.role || "Rol belirtilmedi"} ${item.url ? `/ ${item.url}` : ""}</span>
          <p>${item.description || item.evidence_text || ""}</p>
        </article>`
    )
    .join("");
}

async function openCandidateModal(candidateId) {
  if (!candidateId) return;
  const modal = ensureCandidateModal();
  $(".candidate-modal-body", modal).innerHTML = `<p class="muted-line">Aday detayı yükleniyor...</p>`;
  modal.classList.add("active");
  document.body.classList.add("modal-open");
  const recentResult = (state.recentSearch?.candidates || []).find(
    (candidate) => candidate.candidate_id === candidateId
  ) || {};
  const searchResult = state.lastCandidates.get(candidateId) || recentResult;
  const savedResult = state.savedCandidates.find((candidate) => candidate.candidate_id === candidateId) || {};
  const savedCandidatePayload = savedResult.candidate || {};
  let detail = state.candidateDetails.get(candidateId) || {};
  if (!state.candidateDetails.has(candidateId)) {
    try {
      detail = await api(`/candidates/${candidateId}`);
      state.candidateDetails.set(candidateId, detail);
    } catch (error) {
      detail = {};
    }
  }
  const savedReasons = getSavedCandidateReasons(savedResult);
  const candidate = {
    ...detail,
    ...savedCandidatePayload,
    ...searchResult,
    total_score: searchResult.total_score ?? savedCandidatePayload.total_score ?? savedResult.score ?? detail.total_score,
    score_breakdown: searchResult.score_breakdown || savedCandidatePayload.score_breakdown || savedResult.score_breakdown || detail.score_breakdown,
    reasons: searchResult.reasons || savedCandidatePayload.reasons || (savedReasons.length ? savedReasons : detail.reasons),
  };
  const cvButton = candidate.cv_available
    ? `<a class="primary-btn small" href="${API_BASE}/download-cv/${candidateId}" target="_blank" rel="noreferrer">Hashli CV indir</a>`
    : `<button class="ghost-btn" type="button" disabled>CV yok</button>`;
  const memberBadge = candidate.talentforge_member
    ? `<span class="status-pill">TalentForge üyesi</span>`
    : `<span class="status-pill muted">TalentForge üyesi değil</span>`;
  const messageButton = candidate.talentforge_member && candidate.candidate_user_id && state.role === "hr"
    ? `<button class="primary-btn small" type="button" data-message-candidate-user="${escapeHtml(candidate.candidate_user_id)}" data-message-candidate-id="${escapeHtml(candidateId)}" data-message-job-id="${escapeHtml(candidate.job_context?.id || "")}">Mesaj at</button>`
    : "";

  $(".candidate-modal-body", modal).innerHTML = `
    <div class="modal-head">
      <div>
        <p class="eyebrow">Aday detayı</p>
        <h2>${candidate.name || "Aday"}</h2>
        <p>${candidate.summary || "Ozet bulunamadı."}</p>
      </div>
      <div class="modal-score">
        <span>${candidate.total_score ?? "-"}</span>
        <small>toplam skor</small>
      </div>
    </div>
    <div class="modal-actions">
      ${cvButton}
      <span class="hash-chip">hash: ${candidate.file_hash_short || "yok"}</span>
      ${memberBadge}
      ${messageButton}
    </div>
    <div class="modal-grid">
      <section>
        <h3>Skor kırılımı</h3>
        <div class="breakdown-grid">${formatBreakdown(candidate.score_breakdown)}</div>
      </section>
      <section>
        <h3>İletişim</h3>
        <p class="muted-line">${candidate.email || "-"}<br>${candidate.phone || "-"}<br>${candidate.location || "-"}</p>
      </section>
    </div>
    <section>
      <h3>Eşleşme açıklaması</h3>
      <ul class="reason-list">${(candidate.reasons || []).map((reason) => `<li>${reason}</li>`).join("") || "<li>Açıklama yok.</li>"}</ul>
    </section>
    <section>
      <h3>Yetenekler</h3>
      ${renderPills(candidate.skills, typeof candidate.skills?.[0] === "object" ? "name" : null)}
    </section>
    <section>
      <h3>Deneyim</h3>
      ${renderTimeline(candidate.experiences || [])}
    </section>
    <section>
      <h3>Projeler</h3>
      ${renderProjects(candidate.projects || [])}
    </section>
    <div class="modal-grid">
      <section>
        <h3>Eğitim</h3>
        ${renderPills((candidate.educations || []).map((edu) => [edu.degree, edu.field, edu.institution].filter(Boolean).join(" / ")))}
      </section>
      <section>
        <h3>Sertifika & dil</h3>
        ${renderPills([...(candidate.certifications || []), ...(candidate.languages || [])])}
      </section>
    </div>
  `;
  modal.classList.add("active");
  document.body.classList.add("modal-open");
}

function closeCandidateModal() {
  $(".candidate-detail-modal")?.classList.remove("active");
  if (!$(".job-modal")?.classList.contains("active") && !$(".file-preview-modal")?.classList.contains("active")) {
    document.body.classList.remove("modal-open");
  }
}

async function openJobModal(jobId) {
  const modal = ensureJobModal();
  const cached = state.cache.jobDetails.get(jobId);
  const localJob = cached?.data || state.jobs.find((job) => job.id === jobId) || {};
  let job = localJob;
  renderJobModalBody(modal, job, true);
  modal.classList.add("active");
  document.body.classList.add("modal-open");
  if (cached && nowMs() - cached.at < CACHE_TTL.detail) {
    renderJobModalBody(modal, cached.data, false);
    return;
  }
  if (localJob.description) {
    renderJobModalBody(modal, localJob, false);
    state.cache.jobDetails.set(jobId, { data: localJob, at: nowMs() });
    return;
  }
  try {
    const data = await once(`job:${jobId}`, () => api(`/jobs/${jobId}`));
    job = data.job || localJob;
    state.cache.jobDetails.set(jobId, { data: job, at: nowMs() });
  } catch (error) {
    console.warn(error);
  }
  renderJobModalBody(modal, job, false);
}

function renderJobModalBody(modal, job, isLoading = false) {
  $(".job-modal-body", modal).innerHTML = `
    <div class="modal-head">
      <div>
        <p class="eyebrow">İlan detayı</p>
        <h2>${escapeHtml(job.title || "İlan")}</h2>
        <p>${escapeHtml(job.description || "Açıklama yok.")}</p>
        ${isLoading ? `<p class="muted-line">Detaylar yükleniyor...</p>` : ""}
      </div>
      <div class="modal-score">
        <span>${escapeHtml(job.application_count || 0)}</span>
        <small>başvuru</small>
      </div>
    </div>
    <div class="modal-grid">
      <section>
        <h3>Kriterler</h3>
        <p class="muted-line">
          Kıdem: ${escapeHtml(job.seniority || "Farketmez")}<br>
          Min. deneyim: ${escapeHtml(job.min_experience_years ?? 0)} yıl<br>
          Lokasyon: ${escapeHtml(job.location || "-")}
        </p>
      </section>
      <section>
        <h3>Yetenekler</h3>
        ${renderPills([...(job.must_have_skills || []), ...(job.nice_to_have_skills || [])])}
      </section>
    </div>
    <div class="modal-actions">
      ${state.role === "hr" ? `<button class="primary-btn small" type="button" data-job-applications="${escapeHtml(job.id)}">${job.application_count || 0} başvuru</button>` : ""}
      ${state.role === "hr" ? `<button class="ghost-btn danger" type="button" data-delete-job="${escapeHtml(job.id)}">Sil</button>` : ""}
    </div>
  `;
}

async function deleteJob(jobId) {
  if (!jobId) return;
  const previousJobs = [...state.jobs];
  state.jobs = state.jobs.filter((job) => job.id !== jobId);
  state.cache.jobs = { data: state.jobs, at: nowMs() };
  if (state.dashboardSummary?.metrics) {
    state.dashboardSummary.metrics.active_jobs = Math.max(0, (state.dashboardSummary.metrics.active_jobs || 0) - 1);
    state.cache.dashboard = { data: state.dashboardSummary, at: nowMs() };
  }
  closeJobModal();
  renderJobs();
  refreshHrDashboardSummary();
  try {
    await api(`/jobs/${jobId}`, { method: "DELETE" });
    state.cache.jobDetails.delete(jobId);
    state.cache.jobApplications.delete(jobId);
  } catch (error) {
    state.jobs = previousJobs;
    state.cache.jobs = { data: state.jobs, at: nowMs() };
    invalidateCache("dashboard");
    renderJobs();
    refreshHrDashboardSummary();
    console.warn(error);
  }
}

async function openJobApplicationsModal(jobId) {
  const modal = ensureJobModal();
  const job = state.jobs.find((item) => item.id === jobId) || {};
  $(".job-modal-body", modal).innerHTML = `<p class="muted-line">Başvurular yükleniyor...</p>`;
  modal.classList.add("active");
  document.body.classList.add("modal-open");
  try {
    const cachedApplications = state.cache.jobApplications.get(jobId);
    const data = cachedApplications && nowMs() - cachedApplications.at < CACHE_TTL.detail
      ? cachedApplications.data
      : await once(`jobApplications:${jobId}`, () => api(`/jobs/${jobId}/applications?limit=50&offset=0`));
    state.cache.jobApplications.set(jobId, { data, at: nowMs() });
    const applications = data.applications || [];
    $(".job-modal-body", modal).innerHTML = `
      <div class="modal-head">
        <div>
          <p class="eyebrow">Başvuran adaylar</p>
          <h2>${escapeHtml(job.title || "İlan")}</h2>
          <p>${applications.length} başvuru listeleniyor.</p>
        </div>
      </div>
      <div class="candidate-table in-modal">
        <div class="table-row head"><span>Aday</span><span>Skor</span><span>Profil</span><span>Aksiyon</span></div>
        ${
          applications.length
            ? applications.map((application) => {
                const candidate = application.candidate || {};
                const neo4jId = candidate.neo4j_candidate_id || "";
                const breakdown = application.match_breakdown || {};
                const scoreBreakdown = breakdown.score_breakdown || {};
                const reasons = breakdown.reasons || [];
                const profileLine = [
                  candidate.profession,
                  candidate.school,
                  candidate.location,
                  applicationExperienceLabel(application),
                ].filter(Boolean).join(" / ");
                if (neo4jId) {
                  state.lastCandidates.set(neo4jId, {
                    candidate_id: neo4jId,
                    name: candidate.name,
                    email: candidate.email,
                    location: candidate.location,
                    total_score: application.match_score,
                    score_breakdown: scoreBreakdown,
                    reasons,
                    job_context: {
                      id: jobId,
                      title: job.title || application.job?.title,
                    },
                  });
                }
                return `
                  <div class="table-row">
                    <span>${escapeHtml(candidate.name || "Aday")}</span>
                    <span>${escapeHtml(application.match_score ?? "-")}</span>
                    <span>
                      ${escapeHtml(profileLine || "-")}
                      ${reasons.length ? `<small>${escapeHtml(reasons.slice(0, 2).join(" / "))}</small>` : ""}
                    </span>
                    <span class="row-actions">
                      <button type="button" data-candidate-detail="${escapeHtml(neo4jId)}" ${neo4jId ? "" : "disabled"}>İncele</button>
                      ${neo4jId ? `<a class="ghost-btn" href="${API_BASE}/download-cv/${escapeHtml(neo4jId)}" target="_blank" rel="noreferrer">CV indir</a>` : `<button type="button" disabled>CV yok</button>`}
                    </span>
                  </div>`;
              }).join("")
            : `<div class="table-row"><span>Henüz başvuru yok</span><span>-</span><span>-</span><span>-</span></div>`
        }
      </div>
    `;
  } catch (error) {
    $(".job-modal-body", modal).innerHTML = `<p class="muted-line">${escapeHtml(error.message)}</p>`;
  }
}

function closeJobModal() {
  $(".job-modal")?.classList.remove("active");
  if (!$(".candidate-detail-modal")?.classList.contains("active")) {
    document.body.classList.remove("modal-open");
  }
}

function ensureJobModal() {
  let modal = $(".job-modal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.className = "job-modal candidate-modal";
  modal.innerHTML = `
    <div class="candidate-modal-backdrop" data-modal-close></div>
    <article class="candidate-modal-card wide" role="dialog" aria-modal="true" aria-label="İlan detayı">
      <button class="modal-close" type="button" data-modal-close aria-label="Kapat">×</button>
      <div class="job-modal-body candidate-modal-body"></div>
    </article>
  `;
  document.body.appendChild(modal);
  return modal;
}

function ensureCandidateModal() {
  let modal = $(".candidate-detail-modal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.className = "candidate-modal candidate-detail-modal";
  modal.innerHTML = `
    <div class="candidate-modal-backdrop" data-modal-close></div>
    <article class="candidate-modal-card" role="dialog" aria-modal="true" aria-label="Aday detayı">
      <button class="modal-close" type="button" data-modal-close aria-label="Kapat">×</button>
      <div class="candidate-modal-body"></div>
    </article>
  `;
  document.body.appendChild(modal);
  return modal;
}

function setSearchMode(mode) {
  const panel = $('#hr-dashboard [data-panel="search"]');
  if (!panel) return;
  $all("[data-search-mode-button]", panel).forEach((button) => {
    button.classList.toggle("active", button.dataset.searchModeButton === mode);
  });
  $all("[data-search-mode]", panel).forEach((section) => {
    section.classList.toggle("active", section.dataset.searchMode === mode);
  });
}

function messagesRoot() {
  return $(`[data-role-dashboard="${state.role}"] [data-messages-root]`);
}

function renderMessagesPanel() {
  const root = messagesRoot();
  if (!root) return;
  const active = state.conversations.find((item) => item.id === state.activeConversationId) || state.conversations[0];
  if (active && !state.activeConversationId) state.activeConversationId = active.id;
  root.innerHTML = `
    <section class="messages-list">
      <div class="panel-title-row">
        <h2>Mesajlar</h2>
        ${state.messagesUnread ? `<span class="status-pill">${state.messagesUnread} yeni</span>` : ""}
      </div>
      ${
        state.conversations.length
          ? state.conversations.map((conversation) => {
              const other = conversation.other_user || {};
              const last = conversation.last_message?.body || "Henüz mesaj yok.";
              return `
                <button class="message-thread ${conversation.id === state.activeConversationId ? "active" : ""}" type="button" data-open-conversation="${escapeHtml(conversation.id)}">
                  <strong>${escapeHtml(other.name || "Kullanıcı")}</strong>
                  <span>${escapeHtml(last)}</span>
                  ${conversation.unread_count ? `<b>${conversation.unread_count}</b>` : ""}
                </button>`;
            }).join("")
          : `<div class="empty-state compact"><h3>Henüz mesaj yok</h3>${state.role === "hr" ? "<p>Aday profilinden mesaj başlatabilirsin.</p>" : ""}</div>`
      }
    </section>
    <section class="messages-chat">
      ${
        active
          ? `
            <div class="panel-title-row">
              <div>
                <p class="eyebrow">Konuşma</p>
                <h2>${escapeHtml(active.other_user?.name || "Kullanıcı")}</h2>
              </div>
            </div>
            ${state.activeConversationJob ? `
              <button class="context-card" type="button" data-job-detail="${escapeHtml(state.activeConversationJob.id)}" ${state.activeConversationJob.id ? "" : "disabled"}>
                <span>İlan bağlamı</span>
                <strong>${escapeHtml(state.activeConversationJob.title || "İlan")}</strong>
                <small>${escapeHtml(state.activeConversationJob.location || "Detayı incele")}</small>
              </button>
            ` : ""}
            <div class="message-bubbles">
              ${
                state.activeMessages.length
                  ? state.activeMessages.map((message) => `
                    <article class="message-bubble ${message.sender_user_id === state.user?.id ? "mine" : ""}">
                      <p>${escapeHtml(message.body)}</p>
                    </article>
                  `).join("")
                  : `<p class="muted-line">Bu konuşmada henüz mesaj yok.</p>`
              }
            </div>
            <form class="message-compose" data-message-compose>
              <input name="body" type="text" placeholder="Mesaj yaz..." autocomplete="off" />
              <button class="primary-btn small" type="submit">Gönder</button>
            </form>`
          : `<div class="empty-state compact"><h3>Konuşma seç</h3><p>Mesaj geçmişi burada görünecek.</p></div>`
      }
    </section>
  `;
}

function updateMessageBadges() {
  $all('[data-dash-tab="messages"]').forEach((button) => {
    button.textContent = state.messagesUnread ? `Mesajlar (${state.messagesUnread})` : "Mesajlar";
  });
}

async function loadMessages({ force = false, preferCache = false } = {}) {
  if ((preferCache || !force) && isFresh(state.cache.messages, CACHE_TTL.messages)) {
    const cached = state.cache.messages.data;
    state.conversations = cached.conversations || [];
    state.messagesUnread = cached.unread_count || 0;
    updateMessageBadges();
    renderMessagesPanel();
    return;
  }
  const data = await once("messages", () => api("/messages"));
  state.conversations = data.conversations || [];
  state.messagesUnread = data.unread_count || 0;
  state.cache.messages = { data, at: nowMs() };
  updateMessageBadges();
  if (state.activeConversationId) {
    const exists = state.conversations.some((conversation) => conversation.id === state.activeConversationId);
    if (!exists) state.activeConversationId = null;
  }
  renderMessagesPanel();
  if (state.activeConversationId) await openConversation(state.activeConversationId);
}

async function openConversation(conversationId) {
  state.activeConversationId = conversationId;
  state.activeConversationJob = state.conversationJobs[conversationId] || null;
  const cached = state.cache.conversations.get(conversationId);
  const data = cached && nowMs() - cached.at < CACHE_TTL.messages
    ? cached.data
    : await once(`conversation:${conversationId}`, () => api(`/messages/${conversationId}`));
  state.cache.conversations.set(conversationId, { data, at: nowMs() });
  state.activeMessages = data.messages || [];
  const contextMessage = state.activeMessages.find((message) => (message.body || "").startsWith("İlan bağlamı:"));
  if (contextMessage && !state.activeConversationJob) {
    const title = contextMessage.body.replace("İlan bağlamı:", "").trim();
    const job = state.jobs.find((item) => item.title === title);
    state.activeConversationJob = job ? { id: job.id, title: job.title, location: job.location } : { id: "", title };
  }
  state.activeMessages = state.activeMessages.filter((message) => !(message.body || "").startsWith("İlan bağlamı:"));
  const conversation = data.conversation;
  state.conversations = state.conversations.some((item) => item.id === conversation.id)
    ? state.conversations.map((item) => item.id === conversation.id ? conversation : item)
    : [conversation, ...state.conversations];
  state.messagesUnread = state.conversations.reduce((sum, item) => sum + (item.unread_count || 0), 0);
  updateMessageBadges();
  renderMessagesPanel();
}

async function sendConversationMessage(body) {
  if (!state.activeConversationId || !body.trim()) return;
  const tempMessage = {
    id: `tmp-${Date.now()}`,
    conversation_id: state.activeConversationId,
    sender_user_id: state.user?.id,
    body: body.trim(),
  };
  state.activeMessages = [...state.activeMessages, tempMessage];
  renderMessagesPanel();
  const data = await api(`/messages/${state.activeConversationId}`, {
    method: "POST",
    body: JSON.stringify({ body: body.trim() }),
  });
  state.activeMessages = state.activeMessages.map((message) => message.id === tempMessage.id ? data.message : message);
  const active = state.conversations.find((item) => item.id === state.activeConversationId);
  if (active) {
    active.last_message = data.message;
    active.last_message_at = data.message?.created_at || active.last_message_at;
  }
  state.cache.conversations.set(state.activeConversationId, {
    data: {
      conversation: active || { id: state.activeConversationId },
      messages: state.activeMessages,
    },
    at: nowMs(),
  });
  invalidateCache("messages");
  renderMessagesPanel();
}

async function startMessageWithCandidate(candidateUserId, candidateNeo4jId) {
  await startMessageWithCandidateForJob(candidateUserId, candidateNeo4jId, "");
}

async function startMessageWithCandidateForJob(candidateUserId, candidateNeo4jId, jobId = "") {
  const job = state.jobs.find((item) => item.id === jobId) || null;
  state.activeConversationJob = job ? { id: job.id, title: job.title, location: job.location } : null;
  closeCandidateModal();
  closeJobModal();
  state.suppressMessageLoad = true;
  setDashboardTab("messages");
  state.suppressMessageLoad = false;
  renderMessagesPanel();
  const data = await api("/messages/conversations", {
    method: "POST",
    body: JSON.stringify({
      candidate_user_id: candidateUserId,
      candidate_neo4j_id: candidateNeo4jId,
      job_id: jobId || null,
    }),
  });
  state.activeConversationId = data.conversation?.id || null;
  if (state.activeConversationId && state.activeConversationJob) {
    state.conversationJobs[state.activeConversationId] = state.activeConversationJob;
    persistConversationJobs();
  }
  if (state.activeConversationId) {
    state.conversations = state.conversations.some((item) => item.id === data.conversation.id)
      ? state.conversations.map((item) => item.id === data.conversation.id ? data.conversation : item)
      : [data.conversation, ...state.conversations];
    state.cache.messages = { data: { conversations: state.conversations, unread_count: state.messagesUnread }, at: nowMs() };
    await openConversation(state.activeConversationId);
  }
}

function setupRouting() {
  document.addEventListener("click", (event) => {
    const searchModeButton = event.target.closest("[data-search-mode-button]");
    if (searchModeButton) {
      setSearchMode(searchModeButton.dataset.searchModeButton);
    }

    const detailButton = event.target.closest("[data-candidate-detail]");
    if (detailButton) {
      openCandidateModal(detailButton.dataset.candidateDetail);
    }

    const messageCandidateButton = event.target.closest("[data-message-candidate-user]");
    if (messageCandidateButton) {
      startMessageWithCandidateForJob(
        messageCandidateButton.dataset.messageCandidateUser,
        messageCandidateButton.dataset.messageCandidateId || "",
        messageCandidateButton.dataset.messageJobId || ""
      ).catch((error) => console.warn(error));
    }

    const openConversationButton = event.target.closest("[data-open-conversation]");
    if (openConversationButton) {
      openConversation(openConversationButton.dataset.openConversation).catch((error) => console.warn(error));
    }

    const saveSearchButton = event.target.closest("[data-save-current-search]");
    if (saveSearchButton) {
      saveCurrentSearch();
    }

    const deleteSearchButton = event.target.closest("[data-delete-saved-search]");
    if (deleteSearchButton) {
      deleteSavedSearch(deleteSearchButton.dataset.deleteSavedSearch);
    }

    const runSearchButton = event.target.closest("[data-run-saved-search]");
    if (runSearchButton) {
      const saved = state.savedSearches.find((search) => search.id === runSearchButton.dataset.runSavedSearch);
      if (saved) applySavedSearch(saved);
    }

    const jobDetailButton = event.target.closest("[data-job-detail]");
    if (jobDetailButton) {
      openJobModal(jobDetailButton.dataset.jobDetail);
    }

    const jobApplicationsButton = event.target.closest("[data-job-applications]");
    if (jobApplicationsButton) {
      openJobApplicationsModal(jobApplicationsButton.dataset.jobApplications);
    }

    const deleteJobButton = event.target.closest("[data-delete-job]");
    if (deleteJobButton) {
      deleteJob(deleteJobButton.dataset.deleteJob).catch((error) => console.warn(error));
    }

    const applyJobButton = event.target.closest("[data-apply-job]");
    if (applyJobButton) {
      applyToJob(applyJobButton.dataset.applyJob).catch((error) => console.warn(error));
    }

    const saveCandidateButton = event.target.closest("[data-save-candidate]");
    if (saveCandidateButton) {
      saveCandidate(saveCandidateButton.dataset.saveCandidate);
    }

    const deleteCandidateButton = event.target.closest("[data-delete-saved-candidate]");
    if (deleteCandidateButton) {
      deleteSavedCandidate(deleteCandidateButton.dataset.deleteSavedCandidate);
    }

    const uploadedFileButton = event.target.closest("[data-open-uploaded-file]");
    if (uploadedFileButton) {
      openUploadedFileModal(uploadedFileButton.dataset.openUploadedFile);
    }

    const cvProfileButton = event.target.closest("[data-open-cv-profile]");
    if (cvProfileButton) {
      openCvProfileModal(cvProfileButton.dataset.openCvProfile);
    }

    const deleteCvProfileButton = event.target.closest("[data-delete-cv-profile]");
    if (deleteCvProfileButton) {
      deleteCvProfile(deleteCvProfileButton.dataset.deleteCvProfile).catch((error) => console.warn(error));
    }

    const addCandidateCvButton = event.target.closest("[data-add-candidate-cv]");
    if (addCandidateCvButton) {
      addCandidateCvFromDashboard();
    }

    const closeButton = event.target.closest("[data-modal-close]");
    if (closeButton) {
      if (closeButton.closest(".job-modal")) {
        closeJobModal();
      } else if (closeButton.closest(".file-preview-modal")) {
        $(".file-preview-modal")?.classList.remove("active");
        if (!$(".job-modal")?.classList.contains("active") && !$(".candidate-modal:not(.job-modal):not(.file-preview-modal):not(.cv-profile-modal)")?.classList.contains("active")) {
          document.body.classList.remove("modal-open");
        }
      } else if (closeButton.closest(".cv-profile-modal")) {
        $(".cv-profile-modal")?.classList.remove("active");
        if (!$(".job-modal")?.classList.contains("active") && !$(".file-preview-modal")?.classList.contains("active")) {
          document.body.classList.remove("modal-open");
        }
      } else {
        closeCandidateModal();
      }
    }
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-message-compose]");
    if (!form) return;
    event.preventDefault();
    const input = form.elements.body;
    const body = input.value;
    input.value = "";
    sendConversationMessage(body).catch((error) => console.warn(error));
  });

  $all("[data-route]").forEach((element) => {
    element.addEventListener("click", () => {
      const route = element.dataset.route;
      showView(route === "landing" && state.token ? "dashboard" : route);
    });
  });

  $all("[data-logout]").forEach((element) => {
    element.addEventListener("click", () => {
      clearSession();
      showView("landing");
    });
  });

  $all(".role-option").forEach((button) => {
    button.addEventListener("click", () => {
      state.role = button.dataset.role;
      localStorage.setItem("talentforge_role", state.role);
      syncRoleUI();
    });
  });

  $all("[data-auth-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      $all("[data-auth-tab]").forEach((item) => item.classList.remove("active"));
      $all("[data-auth-panel]").forEach((panel) => panel.classList.remove("active"));
      button.classList.add("active");
      $(`[data-auth-panel="${button.dataset.authTab}"]`)?.classList.add("active");
      setMessage("");
    });
  });

  $all(".dash-link").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.dashTab === "search") renderSearchPanel();
      setDashboardTab(button.dataset.dashTab);
    });
  });

  $("[data-top-action='search']")?.addEventListener("click", () => {
    renderSearchPanel();
    setDashboardTab(state.role === "hr" ? "search" : "matches");
  });
}

function setupLandingUpload() {
  const trigger = $("[data-demo-upload-trigger]");
  const input = $("#demo-cv-input");
  if (!trigger || !input) return;
  trigger.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    uploadLandingCv(input.files?.[0]);
    input.value = "";
  });
}

function setupCandidateCvUpload() {
  const trigger = $("[data-candidate-cv-trigger]");
  const input = $("#candidate-cv-input");
  const continueButton = $("[data-candidate-setup-continue]");
  if (trigger && input) {
    trigger.addEventListener("click", () => input.click());
    input.addEventListener("change", async () => {
      try {
        await uploadCandidateCvs(input.files);
      } catch (error) {
        setCandidateUploadStatus(error.message, "error");
      } finally {
        input.value = "";
      }
    });
  }
  continueButton?.addEventListener("click", () => {
    commitCandidateProfiles().catch((error) => setCandidateUploadStatus(error.message, "error"));
  });
}

function setupAuthForms() {
  $all(".auth-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const panel = form.dataset.authPanel;
      const inputs = [...form.querySelectorAll("input")];
      setMessage("İşleniyor...");

      try {
        if (panel === "forgot") {
          setMessage("Demo modunda şifre sıfırlama simüle edildi.");
          return;
        }

        if (panel === "login") {
          const [email, password] = inputs;
          const data = await api("/auth/login", {
            method: "POST",
            body: JSON.stringify({ email: email.value, password: password.value }),
          });
          saveSession(data);
          setMessage("Giriş başarılı.");
          showView("dashboard");
          return;
        }

        const activeRoleFields = form.querySelector(`[data-register-role="${state.role}"]`);
        const roleInputs = [...activeRoleFields.querySelectorAll("input")];
        const fullName = inputs[0].value;
        const password = inputs[inputs.length - 1].value;
        const payload =
          state.role === "hr"
            ? {
                role: "hr",
                full_name: fullName,
                company_name: roleInputs[0].value,
                company_email: roleInputs[1].value,
                email: roleInputs[1].value,
                position: roleInputs[2].value,
                password,
              }
            : {
                role: "candidate",
                full_name: fullName,
                email: roleInputs[0].value,
                password,
              };

        const data = await api("/auth/register", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        saveSession(data);
        setMessage("Hesap oluşturuldu.");
        if (state.role === "candidate") {
          state.candidateProfiles = [];
          persistCandidateProfiles();
          showView("candidateSetup");
        } else {
          showView("dashboard");
        }
      } catch (error) {
        setMessage(error.message, "error");
      }
    });
  });
}

function setupReveal() {
  const revealEls = $all("[data-reveal]");
  if (!("IntersectionObserver" in window)) {
    revealEls.forEach((el) => el.classList.add("visible"));
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) entry.target.classList.add("visible");
      });
    },
    { threshold: 0.14 }
  );
  revealEls.forEach((el) => observer.observe(el));
}

function setupPresentationNav() {
  const links = $all(".nav-links a[href^='#']");
  if (!links.length) return;

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const sectionId = link.getAttribute("href")?.slice(1);
      const section = sectionId ? document.getElementById(sectionId) : null;
      if (!section) return;

      showView("landing");
      requestAnimationFrame(() => {
        section.scrollIntoView({ behavior: "smooth", block: "start" });
        history.replaceState(null, "", `#${sectionId}`);
      });
    });
  });

  if (!("IntersectionObserver" in window)) return;

  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      links.forEach((link) => {
        link.classList.toggle("active", link.getAttribute("href") === `#${visible.target.id}`);
      });
    },
    { rootMargin: "-28% 0px -58% 0px", threshold: [0, 0.15, 0.4] }
  );

  sections.forEach((section) => observer.observe(section));
}

function setupEvaluationModal() {
  const modal = $("[data-evaluation-modal]");
  if (!modal) return;

  const closeModal = () => {
    modal.classList.remove("active");
    document.body.classList.remove("modal-open");
  };

  $all("[data-evaluation-open]").forEach((button) => {
    button.addEventListener("click", () => {
      modal.classList.add("active");
      document.body.classList.add("modal-open");
    });
  });
  $all("[data-evaluation-close]", modal).forEach((button) => button.addEventListener("click", closeModal));
  $all("[data-evaluation-tab]", modal).forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.evaluationTab;
      $all("[data-evaluation-tab]", modal).forEach((tab) => tab.classList.toggle("active", tab === button));
      $all("[data-evaluation-panel]", modal).forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.evaluationPanel === target);
      });
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("active")) closeModal();
  });
}

function init() {
  setupRouting();
  setupAuthForms();
  setupLandingUpload();
  setupCandidateCvUpload();
  setupReveal();
  setupPresentationNav();
  setupEvaluationModal();
  syncRoleUI();
  renderSearchPanel();

  const initialView = window.location.hash.replace("#", "").split("/")[0];
  const presentationSection = document.getElementById(initialView);
  if (state.token) {
    showView("dashboard");
  } else if (initialView === "guestUpload") {
    showView("guestUpload");
  } else {
    showView("landing");
    if (presentationSection && initialView !== "home") {
      requestAnimationFrame(() => {
        presentationSection.scrollIntoView({ behavior: "auto", block: "start" });
        history.replaceState(null, "", `#${initialView}`);
      });
    }
  }
}

init();


