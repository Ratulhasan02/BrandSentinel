import { useState, useEffect } from "react";
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  const [user, setUser] = useState(null);
  const [err, setErr] = useState("");
  const call = async (path, opts = {}) => {
    const r = await fetch(API + path, { ...opts, headers: { "Content-Type": "application/json", "X-Token": user?.token || "" },
      body: opts.body ? JSON.stringify(opts.body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { setErr(d.detail || "Request failed"); throw new Error(d.detail); }
    setErr(""); return d;
  };
  if (!user) return <Login onLogin={setUser} call={call} err={err} />;
  return (<>
    <header><b>BrandSentinel</b><span>{user.name} ({user.role}) <button className="alt" onClick={() => setUser(null)}>Log out</button></span></header>
    {err && <div className="err" style={{ padding: "0 18px" }}>{err}</div>}
    <Main user={user} call={call} />
  </>);
}

function Login({ onLogin, call, err }) {
  const [name, setName] = useState(""); const [password, setPassword] = useState("");
  return (<div className="card" style={{ maxWidth: 380, margin: "60px auto" }}>
    <h2>BrandSentinel</h2><p className="small">Pre-publication brand review. AI suggests, humans decide.</p>
    <div className="row"><input autoComplete="username" placeholder="Username" value={name} onChange={e => setName(e.target.value)} />
      <input autoComplete="current-password" type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} />
      <button onClick={async () => {
        try { onLogin(await call("/login", { method: "POST", body: { name, password } })); } catch {}
      }}>Log in</button></div>
    <div className="small">Accounts are provisioned by a local administrator; roles cannot be selected here.</div>
    {err && <div className="err">{err}</div>}</div>);
}

function Main({ user, call }) {
  const [tab, setTab] = useState("review"); const [subs, setSubs] = useState([]); const [sel, setSel] = useState(null);
  const load = async () => setSubs(await call("/submissions"));
  useEffect(() => { load(); }, []);
  return (<div className="wrap"><div>
    <div className="row"><button onClick={() => setTab("review")}>Reviews</button>
      <button className="alt" onClick={() => setTab("sources")}>Brand sources</button></div>
    {tab === "review" && <>
      <NewSub call={call} onDone={async id => { await load(); setSel(id); }} />
      <div className="card"><b>Submissions</b>{subs.map(s => <div key={s.id} className={"sub" + (sel === s.id ? " on" : "")} onClick={() => setSel(s.id)}>
        {s.title} <span className="tag">{s.status}</span><div className="small">{s.author} - v{s.version}</div></div>)}</div></>}
  </div><div>{tab === "sources" ? <Sources user={user} call={call} /> : sel ? <Detail key={sel} id={sel} user={user} call={call} refresh={load} /> : <div className="card">Select or create a submission.</div>}</div></div>);
}

function NewSub({ call, onDone }) {
  const [title, setTitle] = useState(""); const [channel, setChannel] = useState("social post"); const [text, setText] = useState("");
  const [uploadError, setUploadError] = useState("");
  const loadSample = () => {
    setTitle("Summer Promotion Ad");
    setChannel("social post");
    setText("Our app is the #1 fastest app in Bangladesh!!! We guarantee that every customer will save 90% on all purchases. Get cheap plans for everyone.");
  };
  const upload = async e => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch(API + "/extract", { method: "POST", body: fd }); const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Could not read the selected file.");
      setUploadError(""); setText(data.text);
    } catch (error) { setUploadError(error.message || "Could not read the selected file."); }
  };
  return (<div className="card"><b>New content</b>
    <div className="row"><input placeholder="Title" value={title} onChange={e => setTitle(e.target.value)} />
      <select value={channel} onChange={e => setChannel(e.target.value)}>{["social post", "website", "press release", "email"].map(c => <option key={c}>{c}</option>)}</select></div>
    <textarea placeholder="Paste content, or upload .txt/.docx" value={text} onChange={e => setText(e.target.value)} />
    <div className="row"><input type="file" accept=".txt,.docx" onChange={upload} />
      <button className="alt" onClick={loadSample}>Load sample post</button>
      <button onClick={async () => {
        try {
          const d = await call("/submissions", { method: "POST", body: { title, channel, text } });
          setText(""); setTitle(""); onDone(d.id);
        } catch {}
      }}>Review content</button></div>
    {uploadError && <div className="err">{uploadError}</div>}
    <div className="small">AI notice: rule checks run on our server. If an LLM key is configured, the text is sent to an external AI service for review.</div></div>);
}

function Highlighted({ text, findings }) {
  const parts = []; let i = 0;
  findings.filter(f => f.status === "pending").forEach(f => {
    if (f.s_from < i) return; parts.push(text.slice(i, f.s_from));
    parts.push(<mark key={f.id} className={f.severity} title={f.why}>{text.slice(f.s_from, f.s_to)}</mark>); i = f.s_to; });
  parts.push(text.slice(i)); return <div className="text">{parts}</div>;
}

function Detail({ id, user, call, refresh }) {
  const [d, setD] = useState(null); const [c, setC] = useState(""); const [reason, setReason] = useState("");
  const [editing, setEditing] = useState(false); const [editText, setEditText] = useState("");
  const load = async () => { setD(await call("/submissions/" + id)); refresh(); };
  useEffect(() => { load(); }, [id]);
  if (!d) return null;
  const act = async (p, body) => {
    try {
      await call(p, { method: "POST", body });
      await load();
      return true;
    } catch { return false; }
  };
  const isFinal = ["approved", "rejected"].includes(d.status);
  const canDecide = ["manager", "reviewer", "admin"].includes(user.role) && d.status === "in_review";
  const canEdit = ["draft", "changes_requested"].includes(d.status) &&
    (user.role === "admin" || (user.role === "creator" && d.author === user.name));
  const canRereview = !isFinal && !(user.role === "creator" && d.status === "in_review");
  const canDecideFindings = ["draft", "changes_requested"].includes(d.status) &&
    (user.role === "admin" || (user.role === "creator" && d.author === user.name));
  return (<><div className="card"><h3>{d.title} <span className="tag">{d.status}</span></h3>
    <div className="small">{d.channel} - by {d.author} - version {d.version}</div>
    {editing ? <><textarea value={editText} onChange={e => setEditText(e.target.value)} />
      <div className="row"><button onClick={async () => { try { await call(`/submissions/${id}`, { method: "PUT", body: { title: d.title, channel: d.channel, text: editText, note: "Manual edit" } }); setEditing(false); await load(); } catch {} }}>Save new version</button>
        <button className="alt" onClick={() => setEditing(false)}>Cancel</button></div></> : <Highlighted text={d.text} findings={d.findings} />}
    <div className="small review-state">
      <b>Review:</b> {d.llm_status === "completed" ? "Deterministic and LLM review completed." :
        d.llm_status === "failed" ? "Deterministic review completed; LLM review failed." :
          d.llm_status === "skipped" ? "Deterministic review completed; LLM review skipped." :
            "Review has not run."}
      {d.llm_detail && <span> {d.llm_detail}</span>}
    </div>
    <div className="row">{canRereview && <button className="alt" onClick={() => act(`/submissions/${id}/rereview`)}>Re-run review</button>}
      {canEdit && !editing && <button className="alt" onClick={() => { setEditText(d.text); setEditing(true); }}>Edit content</button>}
      {!isFinal && ["draft", "changes_requested"].includes(d.status) &&
        (user.role === "creator" && d.author === user.name || user.role === "admin") &&
        <button onClick={() => act(`/submissions/${id}/status`, { status: "in_review" })}>Send to manager review</button>}</div></div>
    <div className="card"><b>Findings ({d.findings.length})</b>
      {d.findings.map(f => (<div key={f.id} className="card" style={{ opacity: f.status === "pending" ? 1 : .5 }}>
        <span className={"tag " + f.severity}>{f.severity}</span> <span className="tag">{f.ftype}</span>
        <span className="tag">{f.origin === "llm" ? "LLM" : "Deterministic"}</span>
        <span className="tag">confidence {Math.round(f.confidence * 100)}%</span> <span className="tag">{f.status}</span>
        <div><b>Flagged:</b> "{f.snippet.trim()}"</div><div><b>Why:</b> {f.why}</div>
        <div className="small"><b>Source:</b> {f.source_title ? `${f.source_title} - ${f.source_body}` : "none found (needs human check)"}</div>
        {f.suggestion ? <div><b>Suggestion:</b> "{f.suggestion}"</div> : <div className="small">No safe automatic suggestion. Edit manually or ask a reviewer.</div>}
        {canDecideFindings && f.status === "pending" && <div className="row"><button disabled={!f.suggestion} onClick={() => act(`/findings/${f.id}/decision`, { decision: "accepted" })}>Accept suggestion</button>
          <button className="bad" onClick={() => act(`/findings/${f.id}/decision`, { decision: "rejected" })}>Reject</button></div>}</div>))}
      {!d.findings.length && <div className="small">No findings. Content matches the approved sources.</div>}</div>
    {canDecide && <div className="card"><b>Decision</b><div className="row"><input placeholder="Reason (needed to approve with high-risk findings)" value={reason} onChange={e => setReason(e.target.value)} style={{ flex: 1 }} />
      <button onClick={() => act(`/submissions/${id}/status`, { status: "approved", reason })}>Approve</button>
      <button className="alt" onClick={() => act(`/submissions/${id}/status`, { status: "changes_requested", reason })}>Request changes</button>
      <button className="bad" onClick={() => act(`/submissions/${id}/status`, { status: "rejected", reason })}>Reject</button></div></div>}
    <div className="card"><b>Comments and activity</b>{d.comments.map(m => <div key={m.id} className="small"><b>{m.author}</b> ({m.role}): {m.body}</div>)}
      <div className="row"><input value={c} onChange={e => setC(e.target.value)} placeholder="Add comment" style={{ flex: 1 }} />
        <button onClick={async () => {
          if (await act(`/submissions/${id}/comments`, { body: c })) setC("");
        }}>Send</button></div></div>
    {!!d.activity.length && <div className="card"><b>Approval activity</b>{d.activity.map((event, index) =>
      <div key={`${event.created}-${index}`} className="small"><b>{event.status}</b> - {event.actor} ({event.role}) - {event.created}
        {event.reason && <div>Reason: {event.reason}</div>}</div>)}</div>}
    <div className="card"><b>Revision history</b>{d.versions.map(v => <div key={v.version} className="small">v{v.version} - {v.author} - {v.created}: {v.note}</div>)}</div></>);
}

function Sources({ user, call }) {
  const [list, setList] = useState([]); const [f, setF] = useState({ kind: "guideline", title: "", body: "", banned: "", preferred: "" });
  const load = async () => setList(await call("/sources")); useEffect(() => { load(); }, []);
  return (<div className="card"><b>Approved brand sources</b>
    {list.map(s => <div key={s.id} className="small"><span className="tag">{s.kind}</span> <b>{s.title}</b>{s.kind === "term" ? `: ${s.banned} -> ${s.preferred}` : `: ${s.body}`}</div>)}
    {user.role === "admin" ? <div><hr /><div className="row"><select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{["guideline", "fact", "term"].map(k => <option key={k}>{k}</option>)}</select>
      <input placeholder="Title" value={f.title} onChange={e => setF({ ...f, title: e.target.value })} />
      {f.kind === "term" ? <><input placeholder="Banned word" value={f.banned} onChange={e => setF({ ...f, banned: e.target.value })} /><input placeholder="Preferred word" value={f.preferred} onChange={e => setF({ ...f, preferred: e.target.value })} /></> :
        <input placeholder="Guideline or approved fact text" value={f.body} onChange={e => setF({ ...f, body: e.target.value })} style={{ flex: 1 }} />}
      <button onClick={async () => {
        try { await call("/sources", { method: "POST", body: f }); await load(); } catch {}
      }}>Add</button></div></div> : <div className="small">Log in as admin to edit sources.</div>}</div>);
}
