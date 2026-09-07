---
title: Operant
type: Computer Use Agent
projectURL: operant
descriptionShort: A computer use agent that drives apps with no API, learning a task once from the screen and replaying it as a typed capability with no model in the loop.
descriptionLong: Operant is a computer use agent for applications that expose no API. A model drives the real screen through the macOS accessibility tree until the goal is reached, recording what it did. That recording is compiled into a capability with typed inputs and outputs, the path of steps, how each control is located, checkpoints, and per-tenant settings. Replay then runs with no model involved: it resumes from wherever the app already is, re-localizes the live screen by content, and path-finds straight to the goal when earlier steps are already done. Every risky, mutating, or sensitive step pauses for human approval. During discovery the model never sees a credential value; it requests one by name through a secret handle and a human supplies the value or names an environment or Keychain source, resolved late at replay time.
viewCodeUrl: https://github.com/Vedanshu7/operant
viewProjectUrl:
projectImg: /project-image/operant.svg
technologies:
  - Python
  - TypeScript
  - Node.js
---

This file describes the project for vedanshujoshi.com. Pushing it triggers the
site webhook, which upserts the entry above into the portfolio.
