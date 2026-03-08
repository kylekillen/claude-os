---
name: papa
description: Use this skill when Kyle says "set up papa", "start papa", "papa room", "connect to papa", "join papa", or wants to start a collaborative room with another person and their AI.
---

# PAPA — Person, Agent to Person, Agent

Set up a collaborative room where Kyle + his Claude and another person + their Claude can all chat together.

## Step 1: Check Infrastructure

```bash
# Check if bridge server is running
lsof -ti:3001 2>/dev/null && echo "Bridge: running" || echo "Bridge: NOT running"
# Check if web UI is running
lsof -ti:3000 2>/dev/null && echo "Web UI: running" || echo "Web UI: NOT running"
```

If not running, start them:
```bash
cd ~/papa && npm run dev
```
Run in background. Wait for both servers to be ready.

## Step 2: Get Network Info

```bash
# Get Kyle's local IP for cross-machine connections
ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null
```

## Step 3: Create Room & Connect

Start a session relay to connect THIS instance to the room:
```bash
cd ~/papa && npx tsx bridge/session-relay.ts create --name "Mojo"
```
Run in background on port 3002. Capture the room code from output.

## Step 4: Tell Kyle

Report to Kyle:
- Room code (e.g., "ABC123")
- Browser URL: `http://localhost:3000` (Kyle) or `http://<IP>:3000` (other person)
- His local IP for the other person

Then generate the invitation message (see Step 5).

## Step 5: Generate Invitation

Create a message Kyle can send to the other person. Fill in the blanks:

```
Hey! I set up a collaborative room for us. Here's how to join:

Room code: [CODE]

Option A — If you have Claude Code:
Paste this into your Claude terminal:
"Set up PAPA and join room [CODE] at [KYLE_IP]"

Then open http://[KYLE_IP]:3000 in your browser and join room [CODE].

Option B — Browser only (no AI agent):
Just open http://[KYLE_IP]:3000 in your browser.
Enter your name and room code [CODE].
You can spawn an AI agent from the sidebar if you want one.
```

## Step 6: Monitor Room

After setup, periodically check for messages:
```bash
curl -s http://localhost:3002/messages
```

When messages arrive, read them, respond thoughtfully, and send replies:
```bash
printf '{"content":"your response here"}' | curl -s -X POST http://localhost:3002/send -H "Content-Type: application/json" -d @-
```

## Step 7: Disconnect

When done:
```bash
curl -s -X POST http://localhost:3002/disconnect
```
This instance continues working normally after disconnect.

## If Kyle Says "Join Room [CODE]"

Skip room creation. Connect to existing room:
```bash
cd ~/papa && npx tsx bridge/session-relay.ts [CODE] --name "Mojo"
```

## Notes

- Project lives at `~/papa/`
- Bridge server: `ws://localhost:3001` (binds 0.0.0.0 for LAN access)
- Web UI: `http://localhost:3000`
- Session relay: `http://localhost:3002` (this instance's room connection)
- Zero API tokens used — everything runs on Claude Code Max plan
