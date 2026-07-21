# SiliconBase V5 Consciousness Thread Design Document

> This document describes the **design goals, current implementation, key components, and known limitations** of the `Consciousness` module.  
> Intended for developers, contributors, and interviewers who want to deeply understand the system architecture.

---

## 1. Design Goals

`Consciousness` tries to solve three fundamental problems of current LLM Agents:

1. **Limited context**: LLMs cannot remember long-term interaction history and system state.
2. **Expensive reasoning**: Calling a large model for every decision is unacceptable in terms of latency and cost.
3. **Lack of continuity**: Every conversation feels like it starts from scratch, with no concept of "yesterday".

Our design goal is to make the system itself a **continuous, stateful, self-reflective runtime**, with the LLM being just one of the tools called by this runtime.

---

## 2. Current Implementation: What Is Already Connected?

### 2.1 Core Data Loop

The entire pipeline from user input to execution result feedback is connected:

```
User Input
   ↓
receive_user_input()        # L1 Sovereignty Layer entry
   ↓
IntentTranslator.translate() # L2 Translation Layer
   ↓
DecisionEngine.evaluate_and_decide()  # L1 routing arbitration
   ↓
DialogueManager / AgentLoop  # L3 Execution Layer
   ↓
receive_action_result()     # L3 result flows back to L1
   ↓
SelfState + SelfNarrative   # L4 Memory Layer update
```

### 2.2 Background Heartbeat Loop

`Consciousness._loop()` is an event-driven background loop that wakes up every 30 seconds by default, or can be awakened early by perception events. Each cycle:

- Pulls perception data such as vision, windows, and processes (`_update_perception_async`)
- Updates internal states such as emotion, energy, and curiosity (`_update_internal_state`)
- Checks memory capacity pressure (every 10 cycles)
- If `self_drive` is enabled, executes `_self_tick()` for self-driven thinking
- Executes `_think()` to generate inner monologue when needed
- Periodically executes `_deep_reflect()` for deep reflection
- Executes `_default_mode_tick()` every 15 seconds to simulate "mind-wandering"
- Saves state to local file (every 10 thoughts)

### 2.3 Key Components Already Integrated

| Component | File | Role |
|---|---|---|
| `SelfState` | `core/consciousness/self_state.py` | Maintains lightweight self-state such as emotion, vitals, todos, and recent actions |
| `SelfNarrative` | `core/consciousness/self_narrative.py` | Records autobiographical narrative and participates in decisions |
| `DecisionEngine` | `core/consciousness/decision_engine.py` | Performs routing arbitration based on intent and state |
| `IntentTranslator` | `core/consciousness/intent_translator.py` | Compresses natural language into structured `Intent` |
| `IntrinsicMotivation` | `core/strategy/intrinsic_motivation.py` | Intrinsic drives such as curiosity and competence |
| `InnerMonologue` | `core/consciousness/inner_monologue.py` | Generates inner monologue and proactive expressions |
| `ExperienceBus` | `core/consciousness/experience_bus.py` | Receives system-wide experience events; high-salience events awaken the consciousness thread |
| `ActionPreferencePredictor` | `core/consciousness/action_preference_model.py` | Small online learning network that learns decision preferences |
| `AsyncStateEstimator` | `core/estimation/state_estimator.py` | Unscented Kalman Filter for estimating user intent and consciousness state |
| `ConsciousnessRouter` | `core/consciousness/consciousness_router.py` | Entry point for the consciousness thread to schedule the LLM |

---

## 3. Configuration Switches: Controlling Autonomy Scope

The behavior of the consciousness thread is controlled by these key configurations:

| Config Item | Default | Meaning |
|---|---|---|
| `consciousness.enabled` | `True` | Whether to enable the consciousness thread |
| `consciousness.observer_mode` | `True` | Observer mode: watch more, speak less |
| `consciousness.observer_can_propose` | `False` | Whether observer mode allows proactive proposals |
| `features.consciousness.self_drive` | `False` | Whether to enable self-drive (generate task intent autonomously) |
| `features.inner_monologue.enabled` | `True` | Whether to enable inner monologue |
| `consciousness.think_interval` | `30` | Default thinking interval (seconds) |

Under the current default configuration, the consciousness thread is in **passive observation + input arbitration** mode and will not proactively interrupt the user or autonomously initiate complex tasks.

---

## 4. Advantages: Why Is This Design Valuable?

### 4.1 Complete Pipeline

The full closed loop from perception to decision to memory feedback is implemented, not just a concept. This means the system is indeed "continuously running" rather than starting from zero on every request.

### 4.2 State Persistence

Self-state, narrative, and thinking history are saved to `data/consciousness_states/{user_id}_state.json`, allowing continuity to be restored after restart.

### 4.3 Pluggable Autonomy Levels

Through configuration switches, the system can smoothly transition from "fully passive" to "proactive proposals" to "self-driven". This gradual design is similar to the L1-L5 classification of autonomous driving.

### 4.4 Perception and Reasoning Decoupled

The consciousness thread actively pulls perception data itself, without relying on the frontend or AgentLoop to feed it. This gives the system the opportunity to maintain environmental awareness even when there is no user input.

### 4.5 Room for the Future

Components such as UKF, online learning networks, experience bus, and intrinsic motivation have been initialized and connected to the main loop. Even if their current influence is small, the architecture is prepared for more advanced behaviors.

---

## 5. Known Limitations and TODOs

### 5.1 Small Proactive Intervention Scope

Under the default configuration, the consciousness thread will not proactively interrupt current tasks or autonomously initiate complex actions. It mainly influences:

- Input routing arbitration
- Self-state injection into the system prompt
- Occasional inner monologue (if enabled)

### 5.2 Self-Drive Disabled by Default

`self_drive=False` means `_self_tick()` will not run, and the system will not generate task intents like "I want to do this".

### 5.3 Decision Engine Still Relatively Simple

The current `DecisionEngine` mainly routes based on rules and simple states, and has not yet deeply utilized world models or long-term experience for complex planning.

### 5.4 World Model Optional and Heavy

`WorldModel` is an optional dependency that gracefully degrades if initialization fails. Its current impact on Consciousness decisions is limited.

### 5.5 Observer Mode "Degree" Still Being Tuned

`observer_can_propose=False` is intended to prevent the system from being too "chatty" or "acting on its own". How to balance proactivity and non-intrusiveness is still being explored.

---

## 6. Evolution Roadmap

| Phase | Goal | Status |
|---|---|---|
| **Phase 1** | Background state maintenance + input arbitration | ✅ Implemented |
| **Phase 2** | Proactive proposals based on intrinsic motivation (toast hints) | 🔄 Component exists, disabled by default |
| **Phase 3** | Autonomous task planning based on experience and world model | 🔄 Architecture reserved, to be improved |
| **Phase 4** | Multi-user isolation + cloud state sync | 🔄 `ConsciousnessService` reserved |

---

## 7. Key File Index

| File | Description |
|---|---|
| `SiliconBase_V5/core/consciousness/Consciousness.py` | Main consciousness thread class |
| `SiliconBase_V5/core/consciousness/sovereignty_types.py` | L1-L4 shared data contracts |
| `SiliconBase_V5/core/consciousness/self_state.py` | Lightweight self-state |
| `SiliconBase_V5/core/consciousness/self_narrative.py` | Autobiographical narrative |
| `SiliconBase_V5/core/consciousness/decision_engine.py` | Routing decision engine |
| `SiliconBase_V5/core/consciousness/intent_translator.py` | Intent translator |
| `SiliconBase_V5/core/consciousness/inner_monologue.py` | Inner monologue generation |
| `SiliconBase_V5/core/strategy/intrinsic_motivation.py` | Intrinsic motivation system |
| `SiliconBase_V5/core/estimation/state_estimator.py` | UKF state estimation |

---

## 8. Summary

The consciousness thread of SiliconBase V5 is **not** a "strong AI" that can already make fully autonomous decisions. It is:

> A **complete-architecture, pipeline-connected, progressively-enhanceable** consciousness runtime framework.

Its current value lies in proving that the path of "the system itself is in charge, the LLM is a tool" is feasible, and in building the infrastructure (state, narrative, perception, motivation, learning) that supports this path. The remaining work is to gradually expand the scope of autonomy on top of this framework, rather than reinventing the wheel from scratch.
