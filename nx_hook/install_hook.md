# PLM Lite NX Hook — Install Instructions (NX 12)

## What it does
`plm_hook.py` runs automatically every time NX 12 starts. It:
- Registers this workstation as an active session with PLM
- Pings PLM when files are opened (keeps session alive)
- Calls checkin on PLM when a checked-out file is saved

All network calls go to the local workstation agent (`localhost:27370`). If the agent isn't running, NX is unaffected — all errors are silently ignored.

---

## Prerequisites
1. **Workstation agent installed** — run `workstation_agent\install.ps1` first
2. **Python available to NX** — NX 12 ships with its own Python; the hook uses only stdlib (`urllib`, `json`, `os`, `socket`) so no extra packages needed

---

## Install steps

### 1. Find your NX 12 startup folder
```
C:\Users\<your-username>\AppData\Local\Siemens\NX 12.0\startup\
```
If the `startup` folder doesn't exist, create it.

### 2. Copy the hook file
```
copy plm_hook.py "C:\Users\<your-username>\AppData\Local\Siemens\NX 12.0\startup\plm_hook.py"
```

### 3. Verify
Start NX 12. In PLM Admin → Cache Sessions you should see this workstation appear within a few seconds of NX loading.

---

## Set your user ID (optional)
The hook reads `PLM_USER_ID` from your Windows environment to identify you:
```
setx PLM_USER_ID 3
```
Replace `3` with your PLM user ID (visible in PLM Admin → Users).

If not set, sessions are recorded as anonymous but still tracked by station name.

---

## Uninstall
Delete `plm_hook.py` from the startup folder. NX will not load it on next start.
