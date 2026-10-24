#!/usr/bin/env python3
"""Safely apply the signup-role patch if the project files are still unpatched.

This script checks that the expected project files exist, verifies whether the
signup-role patch is already present, and only then writes a backup and the
necessary patch. It exits early with 'STOP' if a required path is missing.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_FILE = ROOT / "backend" / "main.py"
FRONTEND_FILE = ROOT / "frontend" / "src" / "App.jsx"


def stop(message: str) -> int:
    print("STOP")
    print(message)
    return 1


def ensure_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")


def backup_file(path: Path) -> Path:
    backup_path = path.with_name(path.name + ".bak")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
    return backup_path


def has_backend_patch(text: str) -> bool:
    required = [
        'create_user(name, "creator", body.password)',
        'class RoleChange(BaseModel):',
        'def change_role(user_id: int, body: RoleChange, x_token: str = Header("")):',
    ]
    return all(item in text for item in required)


def has_frontend_patch(text: str) -> bool:
    required = [
        'New accounts are always creators. Manager and reviewer roles are assigned by an administrator.',
        'function Users({ call }) {',
        'user.role === "admin" && <button className="alt" onClick={() => setTab("users")}>Users</button>',
    ]
    return all(item in text for item in required)


def patch_backend(path: Path, text: str) -> str:
    if has_backend_patch(text):
        return text

    if 'class RoleChange(BaseModel):' not in text:
        marker = "class Register(BaseModel):\n    name: str\n    password: str\n\n\nclass NewSub(BaseModel):\n"
        replacement = (
            'class Register(BaseModel):\n'
            '    name: str\n'
            '    password: str\n\n\n'
            'class RoleChange(BaseModel):\n'
            '    role: Literal["creator", "manager", "reviewer"]\n\n\n'
            'class NewSub(BaseModel):\n'
        )
        if marker in text:
            text = text.replace(marker, replacement)

    if 'create_user(name, "creator", body.password)' not in text:
        anchor = "    if q(\"SELECT count(*) AS n FROM users\", one=True)[\"n\"] >= 500:\n"
        anchor += "        raise HTTPException(429, \"Sign-ups are temporarily closed\")\n"
        if anchor in text:
            replacement = (
                anchor
                + "    try:\n"
                + "        create_user(name, \"creator\", body.password)\n"
                + "    except ValueError as exc:\n"
                + "        raise HTTPException(400, str(exc)) from exc\n"
            )
            text = text.replace(anchor, replacement)

    if 'def change_role(user_id: int, body: RoleChange, x_token: str = Header("")):' not in text:
        marker = "@app.get(\"/users\")\ndef list_users(x_token: str = Header(\"\")):\n    if me(x_token)[\"role\"] != \"admin\":\n        raise HTTPException(403, \"Admin only\")\n    return q(\"SELECT id,name,role,created FROM users ORDER BY id\")\n\n"
        replacement = (
            '@app.get("/users")\n'
            'def list_users(x_token: str = Header("")):\n'
            '    if me(x_token)["role"] != "admin":\n'
            '        raise HTTPException(403, "Admin only")\n'
            '    return q("SELECT id,name,role,created FROM users ORDER BY id")\n\n'
            '@app.post("/users/{user_id}/role")\n'
            'def change_role(user_id: int, body: RoleChange, x_token: str = Header("")):\n'
            '    admin = me(x_token)\n'
            '    if admin["role"] != "admin":\n'
            '        raise HTTPException(403, "Admin only")\n'
            '    target = q("SELECT id,name,role FROM users WHERE id=?", (user_id,), one=True)\n'
            '    if not target:\n'
            '        raise HTTPException(404, "User not found")\n'
            '    if target["role"] == "admin" or target["name"] in DEMO_NAMES:\n'
            '        raise HTTPException(403, "Admin and demo accounts cannot be changed here")\n'
            '    q("UPDATE users SET role=? WHERE id=?", (body.role, user_id), write=True)\n'
            '    for session in TOKENS.values():\n'
            '        if session["name"] == target["name"]:\n'
            '            session["role"] = body.role\n'
            '    return {"ok": True}\n\n'
        )
        if marker in text:
            text = text.replace(marker, replacement)

    return text


def patch_frontend(path: Path, text: str) -> str:
    if has_frontend_patch(text):
        return text

    if 'function Users({ call }) {' not in text:
        marker = "function Main({ user, call }) {\n"
        inject = (
            "function Users({ call }) {\n"
            "  const [list, setList] = useState([]);\n"
            "  const load = async () => setList(await call(\"/users\")); useEffect(() => { load(); }, []);\n"
            "  const setRole = async (id, role) => { try { await call(`/users/${id}/role`, { method: \"POST\", body: { role } }); await load(); } catch {} };\n"
            "  return (<div className=\"card\"><b>Users and roles</b>\n"
            "    <div className=\"small\">Sign-ups start as creators. Change roles here. Admin accounts are created only on the server.</div>\n"
            "    {list.map(u => <div key={u.id} className=\"row\"><span style={{ minWidth: 170 }}>{u.name}</span>\n"
            "      {u.role === \"admin\" ? <span className=\"tag\">admin</span> :\n"
            "        <select value={u.role} onChange={e => setRole(u.id, e.target.value)}>\n"
            "          {[\"creator\", \"manager\", \"reviewer\"].map(r => <option key={r}>{r}</option>)}</select>}</div>)} </div>);\n"
            "}\n\n"
        )
        if marker in text:
            text = text.replace(marker, inject + marker)

    if 'user.role === "admin" && <button className="alt" onClick={() => setTab("users")}>Users</button>' not in text:
        source = '      <button className="alt" onClick={() => setTab("sources")}>Brand sources</button>\n'
        replacement = source + '      {user.role === "admin" && <button className="alt" onClick={() => setTab("users")}>Users</button>}\n'
        if source in text:
            text = text.replace(source, replacement)

    if 'New accounts are always creators. Manager and reviewer roles are assigned by an administrator.' not in text:
        target = '    <div className="small">New accounts are always creators. Manager and reviewer roles are assigned by an administrator.</div>\n'
        if target not in text:
            marker = '    <div className="row"><input autoComplete="username" placeholder="Username" value={name} onChange={e => setName(e.target.value)} />\n'
            if marker in text:
                text = text.replace(marker, target + marker)

    return text


def main() -> int:
    try:
        ensure_file(BACKEND_FILE)
        ensure_file(FRONTEND_FILE)
    except FileNotFoundError as exc:
        return stop(str(exc))

    backend_text = BACKEND_FILE.read_text(encoding='utf-8')
    frontend_text = FRONTEND_FILE.read_text(encoding='utf-8')

    backend_needs_patch = not has_backend_patch(backend_text)
    frontend_needs_patch = not has_frontend_patch(frontend_text)

    if not backend_needs_patch and not frontend_needs_patch:
        print("Signup role patch already present; no changes made.")
        return 0

    if backend_needs_patch:
        backup_file(BACKEND_FILE)
        updated_backend = patch_backend(BACKEND_FILE, backend_text)
        BACKEND_FILE.write_text(updated_backend, encoding='utf-8')
    if frontend_needs_patch:
        backup_file(FRONTEND_FILE)
        updated_frontend = patch_frontend(FRONTEND_FILE, frontend_text)
        FRONTEND_FILE.write_text(updated_frontend, encoding='utf-8')

    print("Signup role patch applied.")
    print(
        f"Backups created at: {BACKEND_FILE.with_name(BACKEND_FILE.name + '.bak')} and "
        f"{FRONTEND_FILE.with_name(FRONTEND_FILE.name + '.bak')}"
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
