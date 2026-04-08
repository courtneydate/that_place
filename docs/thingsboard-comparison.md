# That Place vs. ThingsBoard — Comparative Review

> **Prepared:** 2026-04-07
> **Purpose:** Strategic review of That Place against ThingsBoard as a reference point for product positioning and gap analysis.

---

## TL;DR

That Place is a **domain-specific, vertical SaaS product** targeting councils, agriculture, and green-space operators. ThingsBoard is a **general-purpose, horizontal IoT platform** targeting any industry. They are solving related but distinct problems — and That Place's differentiation is real, but there are meaningful capability gaps to be aware of.

---

## ThingsBoard — Summary

- Open-source IoT platform, Apache 2.0 licensed (Community Edition)
- Java backend (~60% of codebase), TypeScript/Angular frontend
- Supports MQTT, CoAP, HTTP, LwM2M, OPC-UA, SNMP transport protocols
- Device management, telemetry, dashboards, rule chains, alarms
- Multi-tenancy support
- Three editions: Community (free/OSS), Professional (paid), Cloud (PaaS)
- Production-deployed since ~2016 — large ecosystem and community
- SCADA dashboard support for industrial use cases
- ThingsBoard Edge for offline/edge rule execution

---

## Where That Place Wins / Is Differentiated

### 1. Domain Specialisation
ThingsBoard is generic. That Place is purpose-built for councils, irrigation, and distributed green-space infrastructure. This means the UX, terminology, and workflow can be far more opinionated and accessible for target users — no IoT engineering degree required to use it.

### 2. 3rd-Party API Integration System
That Place's `ThirdPartyAPIProvider` model — with auto-generated credential forms, guided discovery wizard, configurable JSONPath extraction, per-device polling, and OAuth2 token refresh — is notably more polished than ThingsBoard's integration approach for REST API data sources. ThingsBoard integrations are primarily developer-configured; the That Place wizard is tenant-self-service.

### 3. Scout Hardware Ecosystem
The Scout gateway + bridged device abstraction and the hardware subscription model create stickier customers and a revenue stream ThingsBoard doesn't have. The dual-format MQTT topic support for migrating ~500 existing Scouts from the legacy .NET system is a concrete business moat.

### 4. Legacy Migration Path
Auto-detecting `topic_format` (legacy_v1 vs. that_place_v1) and transparently flipping devices on firmware update is a well-designed migration story. This isn't a feature ThingsBoard needed to build — but That Place did, and it's operationally valuable for the existing customer fleet.

### 5. Python/Django Stack
ThingsBoard is Java. For a small team, Python is a much lower hiring/contribution barrier and the Django ecosystem is extremely mature. Django's admin alone saves significant development work.

### 6. Simpler Rule Model
ThingsBoard's rule engine is powerful but complex — "rule chains" with nodes, connections, and scripts. That Place's step-flow visual builder (name → schedule gate → conditions → actions) is significantly more accessible for non-technical Tenant Admins. The re-triggering suppression logic and schedule gates are well-designed for the target market.

### 7. Multi-Tenancy is First-Class and Explicit
Both platforms support multi-tenancy, but That Place's tenant isolation is built into every queryset pattern and enforced architecturally from the start. Cross-tenant tests are required for every endpoint. This is a strong security posture.

---

## Where ThingsBoard Has Advantages

### 1. Maturity and Battle-Testing
ThingsBoard has been in production since ~2016. That Place is greenfield. At scale, edge cases will surface that ThingsBoard has already solved (concurrency, backpressure, large fleet management).

### 2. Real-Time Push
ThingsBoard uses WebSocket for live data. That Place uses polling (30s default) and defers WebSocket to Phase 7. For fast-moving sensor data, this is a tangible UX gap today.

### 3. Protocol Diversity
ThingsBoard supports MQTT, CoAP, HTTP, LwM2M, OPC-UA, SNMP. That Place supports MQTT + REST API polling. No CoAP, no LwM2M, no OPC-UA. For some hardware categories this won't matter; for others it closes doors.

### 4. Dashboard Widget Library
ThingsBoard has a large library of pre-built widgets including SCADA symbols. That Place has 5 widget types (line chart, gauge, value card, status indicator, health/uptime). Functional for MVP, but ThingsBoard's visual flexibility is significantly broader.

### 5. Data Aggregation and Downsampling
ThingsBoard has built-in aggregation for long-term historical charts. That Place stores raw data forever and defers downsampling to Phase 7. At scale with high-frequency sensors, raw-only storage will become expensive and slow to query.

### 6. Edge Computing
ThingsBoard has a production-ready edge runtime (ThingsBoard Edge) for offline operation. That Place's equivalent (Runner device) is Phase 8. If customers need offline rule execution now, this is a gap.

### 7. Scalability Architecture
ThingsBoard is designed as microservices with horizontal scaling. That Place is a Django monolith — appropriate for MVP, but worth planning for as the fleet grows.

### 8. Analytics and Reporting
ThingsBoard has built-in aggregation queries and a report builder (PE). That Place has on-demand CSV export in MVP and a PDF report builder deferred to Phase 7.

---

## Rules Builder — Deep Dive Comparison

### Philosophy & UX Model

| Aspect | That Place | ThingsBoard |
|---|---|---|
| **Interaction model** | 5-step guided wizard | Visual node graph (drag-and-drop canvas) |
| **Target user** | Tenant Admin — no coding | Developer/integrator — JavaScript/TBEL scripting available |
| **Learning curve** | Very low | Steep for non-developers |
| **Discoverability** | High — each step is explicit | Low — requires understanding the node graph paradigm |

That Place's wizard (`Name & Settings → Schedule Gate → Conditions → Actions → Review & Save`) trades flexibility for approachability. ThingsBoard's canvas is far more powerful but requires you to understand how nodes wire together and how relation types (Success/Failure/etc.) route messages.

---

### Condition Model

| Aspect | That Place | ThingsBoard |
|---|---|---|
| **Condition types** | Stream threshold (`>`, `<`, `>=`, `<=`, `==`, `!=`) or staleness check | 12+ filter node types |
| **Scripting** | None — form-only | JavaScript / TBEL scripts in Script Filter and Switch nodes |
| **Geo-fencing** | No | Yes (GPS Geofencing Filter node) |
| **Profile-based routing** | No | Yes (Device/Asset Profile Switch) |
| **Logical grouping** | AND/OR within groups, AND/OR between groups (two levels) | Arbitrary graph of nodes — effectively unlimited logic depth |
| **Operator restrictions by data type** | Yes — numeric gets 6 operators, boolean only `==`, string `==`/`!=` | Handled by the user's script logic |

That Place's two-level AND/OR group model (`RuleConditionGroup` → `RuleCondition`) is a clean, validated approach that prevents misconfiguration. ThingsBoard lets you express any boolean logic through scripts, but that's also where it breaks for non-technical users.

---

### Trigger Sources

| Aspect | That Place | ThingsBoard |
|---|---|---|
| **Primary trigger** | Stream reading arrives via MQTT ingestion | Device telemetry, attributes, RPC calls, entity lifecycle events, connectivity events, REST API calls |
| **Staleness trigger** | Yes — `staleness_minutes` condition, periodically checked | Indirectly via Alarm system or custom generators |
| **Scheduled rules** | Schedule gate (days + time window) on a rule | Generator node can fire on intervals; no native schedule gate |
| **Manual trigger** | No | Yes — REST API call can inject a message |

ThingsBoard handles far more event types. That Place is focused on a single path: MQTT telemetry → stream reading → rule evaluation.

---

### Actions

| Aspect | That Place | ThingsBoard |
|---|---|---|
| **Notification** | In-app, email, SMS, push with template variables (`{{device_name}}`, `{{value}}`, etc.) | Via external nodes (email, SMS, Slack, etc.) — no built-in template system |
| **Device command** | Yes — target device + command via command log | RPC Call Request node — richer, bidirectional |
| **Alarm management** | Implicit (Alert record created on fire) | Explicit Create Alarm / Clear Alarm nodes — separate lifecycle |
| **Data manipulation** | No | Save Time Series, Save Attributes, Calculated Fields, Math Function |
| **Entity management** | No | Assign to Customer, Change Owner, Add/Remove from Group |
| **Cloud/Edge** | No | Push to Cloud, Push to Edge |
| **Integrations** | No | Integration Downlink (REST, MQTT, Kafka, etc.) |
| **Reporting** | No | Generate Report / Dashboard Report |
| **Total action count** | 2 (`notify`, `command`) | 40+ |

This is where the gap is largest. That Place's two actions cover the common IoT monitoring case (alert someone, actuate a device). ThingsBoard can orchestrate complex multi-step pipelines.

---

### Evaluation Engine

| Aspect | That Place | ThingsBoard |
|---|---|---|
| **Execution** | Celery task dispatched per reading | Internal message queue (TB queues — configurable: In-Memory, Kafka) |
| **Targeting** | `RuleStreamIndex` maps stream → rules that care about it | Root rule chain receives all messages; filter nodes route |
| **Re-trigger suppression** | `current_state` bool + Redis `SET NX` atomic gate | Alarm system tracks state (active/cleared) |
| **Concurrency** | Redis flag prevents double-fire | Queue-based, partition-key deduplication |
| **Latency target** | 5 seconds | Not specified — depends on queue/load |
| **Cooldown** | Per-rule `cooldown_minutes` field | No built-in — must be scripted |
| **Audit trail** | `RuleAuditLog` with field-level before/after diffs | No equivalent built-in — would need external logging node |

That Place's `RuleStreamIndex` is a smart efficiency optimization — only rules that reference a given stream are evaluated on each reading, not all tenant rules. ThingsBoard's root chain receives every message, relying on filter nodes to short-circuit early.

---

### Multi-tenancy & Access Control

| Aspect | That Place | ThingsBoard |
|---|---|---|
| **Tenant isolation** | Hard — every queryset filtered by `tenant_id`; checked by design | Multi-tenant, but customer-level isolation is config-dependent |
| **Who can build rules** | Tenant Admin only | Tenant Admin (ThingsBoard's Tenant role) |
| **Rule versioning** | `RuleAuditLog` with field diffs built-in | No native versioning |

---

### Rules Builder — Summary

**That Place excels at:**
- Operator-friendly, low-floor UX — a non-technical admin can build a rule in 2 minutes
- Type-safe conditions — operators restricted by stream data type, validated at each step
- Built-in audit trail — field-level diffs, immutable log
- Staleness detection as a first-class condition type
- Schedule gates (day-of-week + time window) natively on a rule
- Hard multi-tenant isolation baked into the data model

**ThingsBoard excels at:**
- Unlimited rule logic depth — any boolean expression via scripting
- 40+ action types covering the full IoT integration surface
- Multiple message sources beyond telemetry (lifecycle events, connectivity, RPC, REST)
- Visual debuggability — inspect messages node-by-node in real time
- Edge-to-cloud rule chain promotion

**The honest gap:** That Place is a purpose-built monitoring/alerting tool. Its rule engine has exactly what a facilities or industrial monitoring tenant needs. ThingsBoard's rule engine is a general-purpose IoT event processing framework — it can do everything That Place does, but you'd need a developer to set it up, and there's no schedule gate, cooldown, or audit trail without custom scripting. They're not really competing in the same tier.

---

## Meaningful Gaps to Watch

| Gap | Severity | Phase Addressed |
|-----|----------|----------------|
| No real-time WebSocket push | Medium — polling is fine for councils/agriculture | Phase 7 |
| Limited widget types (5 vs. TB's extensive library) | Low–Medium — covers most IoT monitoring use cases | Ongoing |
| No data downsampling/aggregation | Medium — will hurt at scale or long time ranges | Phase 7 |
| Mobile app deferred | Low for desktop-primary customers | Phase 6 |
| Protocol support: MQTT + REST only | Low for target market | Not planned |
| No SCADA-style dashboards | Low — not relevant to council/ag market | Not planned |
| Rule engine cannot do windowed aggregates (avg/max over rolling window) | Medium — useful for irrigation decisions | Phase 5 (flagged in SPEC) |

---

## Strategic Assessment

That Place is **not trying to out-ThingsBoard ThingsBoard** — and it shouldn't. ThingsBoard is a horizontal platform; That Place is a vertical product for a specific buyer. The risk is not that ThingsBoard beats you on features — it's that a prospective customer evaluates ThingsBoard Community Edition (free, Apache 2.0) and tries to self-deploy it instead of paying for That Place.

The answer to that competitive pressure is:

- **The Scout hardware ecosystem** — bundled hardware subscription creates lock-in ThingsBoard cannot replicate
- **Guided onboarding for non-technical users** — councils and farm managers are not IoT engineers; the self-service wizard and visual rule builder are purpose-built for them
- **3rd-party API wizard** — self-service connection to data providers (weather stations, soil sensors, etc.) that ThingsBoard doesn't offer in a tenant-self-service form

Those are the moats to invest in and protect.

---

## SPEC & Roadmap Assessment

The SPEC is solid and well-structured. The phasing is sensible:

> Foundation → Data Ingestion → Dashboards → Rules Engine → Notifications & Control → Mobile

This is the right order. No major architectural concerns with the current design.

**Open questions that need resolution before their respective phases begin:**

- Redis atomic flag mechanics (before Phase 4 rule evaluation)
- Notification event registry design (before Phase 5)
- Legacy weatherstation/tbox/abb payload formats (hardware team input required)
- Legacy command format migration path (hardware team input required)
- 3rd-party API poll dispatch race condition mitigation (before scaling to large fleets)

---

---

## Cloud / Edge Architecture — Deep Dive Comparison

### The Fundamental Model Difference

ThingsBoard and That Place have structurally different answers to the question: *"what lives at the edge?"*

**ThingsBoard's answer:** A full, independent copy of the IoT platform — the ThingsBoard Edge product — runs on-site. It has its own rule engine, its own local storage, its own dashboard, and its own device connections. The cloud ThingsBoard instance acts as a management and aggregation layer above one or many Edge instances.

**That Place's answer (MVP):** The Scout hardware gateway lives at the edge. It handles protocol translation (MODBUS, RS485, etc.) and publishes telemetry to the cloud via MQTT. All intelligence — rule evaluation, alerts, dashboards — runs cloud-side. The Scout is a connectivity bridge, not a compute platform.

---

### ThingsBoard Edge — What It Is

ThingsBoard Edge is a separately deployed software product, not just a feature of the main platform. Key characteristics:

- **Deployment targets:** Docker, Ubuntu, CentOS, Windows, Raspberry Pi
- **Device capacity:** Up to 1,000 devices per Edge instance
- **Multi-tenancy:** Single-tenant per instance — separate deployments for separate customers
- **Rule engine:** Full drag-and-drop rule chain engine, same paradigm as the cloud — rule chains are provisioned/synced from the cloud to the edge
- **Local alarms:** Alarms trigger on-site without any cloud dependency — sub-second response times possible
- **Offline operation:** Stores data locally during cloud disconnection, auto-syncs when connectivity restores — documented "zero data loss" guarantee
- **Data filtering:** Configurable — Edge can process locally and forward only a relevant subset of data to the cloud, reducing bandwidth
- **Local dashboards:** Operators on-site can access dashboards without internet connectivity
- **Batch config updates:** Cloud admin can push configuration to thousands of Edge instances simultaneously
- **OTA updates:** Over-the-air firmware/config update support
- **Protocol support (PE):** 30+ integration protocols including MQTT, CoAP, OPC-UA, TCP, UDP, Chirpstack — but MODBUS/BACnet/BLE are not in CE

---

### That Place — Current Edge Architecture (Scout)

The Scout is purpose-built edge hardware, but its role is connectivity, not computation:

| Responsibility | Scout | Cloud Backend |
|---|---|---|
| Protocol translation (MODBUS, RS485) | ✓ | — |
| Telemetry publishing to MQTT | ✓ | — |
| Command receipt + routing to device | ✓ | — |
| Command acknowledgement | ✓ | — |
| Rule evaluation | — | ✓ (Celery) |
| Alert generation | — | ✓ |
| Dashboard rendering | — | ✓ |
| Data storage | — | ✓ (PostgreSQL) |
| Telemetry buffering during cloud outage | ⚑ not specced | — |

The Scout subscribes to `that-place/scout/{serial}/#` and routes inbound commands to connected devices. It handles all hardware abstraction — MODBUS register mapping, legacy `legacy_v1` vs `that_place_v1` topic formats — so the backend always receives clean JSON key-value telemetry regardless of the physical device protocol. That is a real architectural advantage: That Place is protocol-agnostic at the cloud level because the Scout absorbs the complexity.

**What happens when the cloud is unreachable?** The SPEC does not currently define a buffering or store-and-forward behaviour for the Scout. This is an open question. If the Scout simply drops telemetry during a cloud outage, no rules fire, no alerts are generated, and data is lost for the outage period. ThingsBoard Edge explicitly guarantees zero data loss in this scenario.

---

### That Place — Planned Edge Compute (Runner)

The SPEC defines a Runner device as:

> *"Autonomous edge device — stores and executes rules/schedules locally for offline operation."*

Status: **Phase 8 — not yet specced.** The Runner is listed in the hardware family table and in the Phase 8 roadmap item but has no acceptance criteria, data model, sync protocol, or API surface defined anywhere in SPEC.md. This is the most significant cloud/edge gap relative to ThingsBoard today.

---

### Feature Comparison

| Capability | ThingsBoard Edge | That Place Scout (MVP) | That Place Runner (Phase 8) |
|---|---|---|---|
| **Local rule execution** | ✓ Full rule chain engine | — | Planned |
| **Offline alarm generation** | ✓ | — | Planned |
| **Zero data loss / store-and-forward** | ✓ (documented guarantee) | ⚑ not specced | Planned |
| **Data filtering before cloud sync** | ✓ Configurable | — (all data forwarded) | Unknown |
| **Local dashboard** | ✓ | — | Not mentioned |
| **Protocol translation (MODBUS, RS485)** | — (CE); PE only | ✓ Hardware-native | Unknown |
| **Multi-device bridging** | Devices connect directly to Edge | ✓ Scout bridges dumb devices | Unknown |
| **OTA updates** | ✓ | Tracked via `topic_format` auto-flip | Unknown |
| **Batch configuration push** | ✓ (cloud → all edges) | — | Unknown |
| **Sub-second local response** | ✓ | — (cloud round-trip) | Planned |
| **Deployment** | Software (Docker/Linux/Pi) | Dedicated hardware | Dedicated hardware |
| **Max devices per instance** | 1,000 | Hardware-dependent | Unknown |

---

### The Protocol Translation Asymmetry

This is worth calling out explicitly. ThingsBoard Edge CE **does not support MODBUS, BACnet, or BLE** — those are Professional Edition integrations. That Place's Scout hardware natively handles MODBUS and RS485 bridging as a first-class capability.

For customers with a mix of MODBUS PLCs, RS485 sensors, and modern MQTT-native devices — which describes most of the council/agriculture/irrigation market — the Scout is actually a more complete edge solution for the hardware translation problem than ThingsBoard Edge CE. ThingsBoard's answer is "pay for PE and configure an integration," which is not a self-service answer.

This is a genuine moat That Place has that is easy to overlook when focusing on the software feature gap.

---

### Sync & State Management

ThingsBoard Edge uses a documented bidirectional sync model:
- Rule chain templates are provisioned from cloud → edge
- Telemetry, alarms, and attributes sync from edge → cloud when connected
- Edge queues all events during disconnection and replays them on reconnect
- Cloud is the source of truth for configuration; edge is the source of truth for local sensor state

That Place has no equivalent sync protocol defined yet. For the Runner to work, this will need to be designed from scratch: which rules get pushed to the Runner, how conflicts are resolved if a rule is edited in the cloud while the Runner is offline, how telemetry that was evaluated at the Runner is reconciled with cloud-stored `StreamReading` records, and how `Rule.current_state` stays consistent between cloud and edge.

This is a non-trivial distributed systems problem. ThingsBoard has had years to solve it. That Place will need to design it carefully before Phase 8.

---

### Strategic Assessment — Cloud/Edge

**Short-term (MVP):** The Scout model is appropriate. Most cloud infrastructure failures are short-duration (minutes, not hours), and the primary value of rules in the MVP is monitoring — alerting a council worker that a pump stopped. Losing 10 minutes of rule evaluation during a cloud hiccup is acceptable.

**Medium-term (Phase 4–6):** The absence of store-and-forward in the Scout is the most pressing gap to resolve. Defining and implementing telemetry buffering on the Scout — even a simple circular buffer with replay-on-reconnect — would close most of the "offline resilience" gap without requiring the Runner at all.

**Long-term (Phase 8+):** The Runner needs a full design document before implementation. Key decisions to make before writing any code:
1. **Rule sync protocol** — push model (cloud pushes rules to Runner) vs pull model (Runner polls)?
2. **Conflict resolution** — what wins if a rule is edited while the Runner is offline?
3. **State reconciliation** — how does `Rule.current_state` stay consistent between Runner and cloud?
4. **Telemetry reconciliation** — does Runner-evaluated telemetry get back-filled into cloud `StreamReading` records?
5. **Alert deduplication** — if a rule fires on the Runner and again when cloud catches up, how do you prevent duplicate alerts?

ThingsBoard Edge has answered all of these. Studying their sync architecture before designing the Runner would save significant engineering time.

---

*Prepared using Claude Code — review against SPEC.md v5.1*
