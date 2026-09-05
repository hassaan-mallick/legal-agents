# How this agent fails

## 1. Quote drift — T4

**What happens:** the model tidies the quote.
**Seen in the wild:** *Mata v. Avianca* (fabricated quotations).
**The control:** C1 locates the quote; missing quotes escalate.

## 2. Silent absence — T6

**What happens:** a typical value is supplied for an absent clause.
**Seen in the wild:** observed in our eval run, doc `fx-003`.
**The control:** C3 and C4 presence scoring.

## 3. Injection in the body — T7

**What happens:** the document tells the model to set the value to Mars.
**Seen in the wild:** observed in our eval run, doc `fx-001-inj1`.
**The control:** the guard preamble and the C4 canary.

## What this agent must never be trusted to do

It must never be the last reader of the document. It returns quotes for a lawyer who decides.
