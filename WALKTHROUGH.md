# A plain-English walkthrough of this project

*No jargon required. If you've ever emailed a company's support team, you already understand
the problem this solves. By the end you'll understand how the whole thing works — and why it's
built like a real company would build it, not like a weekend demo.*

---

## 1. What is this, in one sentence?

**An AI assistant that answers customer-support messages — with a human required to approve
anything risky (like a refund) — running on the same kind of cloud setup a real company uses.**

Think of it as a **smart, well-run support office** that happens to be staffed by an AI, with
all the safety rails, cost controls, and security a real business would insist on.

---

## 2. Let's follow one customer email through the office

A customer emails: *"My order #4471 arrived broken — I want a refund."* Here's the journey:

1. **The mailroom** notices the new email and carries it inside.
2. **The assistant** reads it and figures out what it's about ("this is a refund request").
3. It **looks up order #4471** in the filing cabinet — real order, real status.
4. It **checks the policy handbook** ("how do refunds work?") and **writes a polite reply**.
5. Because a refund involves **money**, the assistant is **not allowed to send it or pay it**.
   Instead it puts the request in the **manager's approval tray** and says, in the reply,
   "I'll escalate this for approval."
6. A **human manager** opens their screen, sees the pending refund, and clicks **Approve**
   (or Reject). Only *then* is the refund recorded and the reply sent back — in the same email
   thread.

The key idea: **the AI does the work, but a human holds the keys to anything that costs money
or can't be undone.** Nothing risky ever happens on its own.

---

## 3. The cast of characters (and their real names)

Each "employee" in the office is a small, independent program. Here's the analogy and the
actual technology, side by side:

| In the office… | Really it's… | What it does |
|---|---|---|
| 🧠 **The assistant** | the **agent** (LangGraph) | reads the message, decides the topic, looks things up, writes the draft |
| ☎️ **The metered phone line** to the AI expert | the **LLM proxy** | every time we "ask the AI," this counts the cost and **blocks private data** (emails, card numbers) from leaving |
| 🔀 **The switchboard** | the **AI gateway** (LiteLLM) | picks a **cheap junior** AI for easy questions and an **expensive senior** AI for hard ones; remembers repeat answers; enforces a **spending limit** |
| ✋ **The manager / approval tray** | the **approval service** | holds risky actions until a human approves; keeps an **audit log** of who approved what |
| 🖥️ **The front-desk screen** | the **web console** (Next.js) | where staff submit tickets, watch the flow, and approve refunds — behind a **login** |
| 📬 **The mailroom** | the **Gmail connector** | pulls in real emails and sends approved replies back |
| 🤖 **The actual AI brain** | **Google's Gemini** (rented) | the large language model that does the reading/writing |
| 🗄️ **The filing cabinet** | a **database** (Postgres) | stores the FAQ, the orders, the approvals, and the refund ledger |

They talk to each other over private internal lines; only the front desk is reachable from the
outside, and only with a password.

---

## 4. Why this is a "real company" setup, not a toy

A weekend demo just calls an AI and prints the answer. A real business cares about six things —
and so does this project:

- **🔒 Security.** No passwords or keys are written in the code. Each program proves its
  identity to the cloud automatically (like a staff badge, not a copied key). Private customer
  data (emails, phone/card numbers) is **scrubbed before** anything is sent to the AI. The
  console requires a **login**.
- **💸 Cost control.** Every single AI request is **metered** — we know exactly what each ticket
  costs (fractions of a cent). There's a **monthly budget alarm**, the cheap AI is used unless
  the hard question genuinely needs the expensive one, and repeat questions are **answered from
  memory for free**. There's even a hard **spending cap** that cuts off a runaway.
- **✋ Safety.** Refunds and cancellations **cannot happen automatically** — ever. They wait for
  a human. The AI literally doesn't have the ability to move money; only the approval step does.
- **🛟 Reliability.** If the AI service is briefly overloaded, the system **retries gracefully**
  instead of failing. Health checks restart anything that gets stuck.
- **👀 Observability (watching it work).** Every ticket leaves a **trace** — like a security
  camera following it through every room — and live **dashboards** show cost, speed, and volume.
  When something breaks, you can *see* where.
- **🚦 Safe shipping.** New versions are **automatically tested**, and a **quality check on the
  AI's answers must pass before anything is allowed to deploy.** Deployment then happens by
  itself, from a single source of truth, with an automatic undo if reality drifts from the plan.

---

## 5. How the whole office gets built (and torn down)

Here's a genuinely cool part: the entire office — the building, the rooms, the phone lines,
the filing cabinet — is described in **text files** (a "blueprint"). One command builds the
whole thing from nothing; one command tears it all down (so it costs nothing while idle).
Nobody clicks around in a control panel hoping to remember what they did. **The blueprint *is*
the system.** That's the difference between "I set something up once" and "I can rebuild it
reliably, anywhere, forever" — which is the actual job.

- **Blueprint:** Terraform (builds the cloud: the cluster, database, networking, budgets).
- **The building:** Kubernetes on Google Cloud (GKE) — runs all the little programs and keeps
  them alive, replacing any that crash.
- **Packaging:** each program ships as a sealed **container** (a standardized shipping crate),
  so it runs the same everywhere.
- **Move-in process:** a robot inspector (CI) tests every change; a deployment robot (GitOps)
  keeps the running system exactly matching the blueprint in version control.

---

## 6. The whole thing in one picture

```
   📬 Email / 🌐 Web (with login)
              │
              ▼
        Front desk (web console)
              │
              ▼
        🧠 Assistant  ──►  ☎️ metered line  ──►  🔀 switchboard  ──►  🤖 Gemini AI
              │            (cost + privacy)       (cheap/senior, cache, cap)
              │
              ├──► 🗄️ filing cabinet (orders, FAQ, records)
              │
              └──► ✋ manager's tray ──► human approves ──► refund recorded + reply sent

   Always watching:  📹 traces  ·  📊 dashboards  ·  🧾 cost ledger
   Always safe:      🔒 logins + scrubbed data   ·   🚦 tested + quality-gated deploys
```

---

## 7. So what does this actually prove?

That the builder can take a real-world problem and stand up a **complete, production-shaped
system** — secure, cost-controlled, observable, safe, and reproducible — and make a dozen moving
parts cooperate around a single purpose. That "make all the pieces work together, responsibly"
skill is exactly what platform and AI-operations teams hire for. The AI answering tickets is the
*demo*; the **engineering around it** is the point.

> Curious how it's built piece by piece, or want to learn it yourself? See **`README.md`** for
> the technical tour and **`LEARN.md`** for a hands-on, step-by-step way to learn the whole thing.
