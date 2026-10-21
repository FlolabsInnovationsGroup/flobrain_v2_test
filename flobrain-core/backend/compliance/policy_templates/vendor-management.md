# Vendor management policy

**Organization:** {{ORG_NAME}}
**Owner:** {{POLICY_OWNER}}
**Effective:** {{EFFECTIVE_DATE}}
**Review:** every 12 months

> Template. Adjust it to your setup before you publish it.

## 1. Scope

Any outside company that stores, processes or can reach our information: hosting, AI model providers,
software services, outside AI agents connected to FloBrain, and contractors.

## 2. Before we start

- Write down what the vendor does for us, what data it gets, and where that data is stored.
- Check its security: a current SOC 2 report or ISO 27001 certificate, or answers to our questionnaire.
- Sign a contract that covers confidentiality, data protection (a data processing agreement where personal
  data is involved), breach notification and what happens to our data when we stop.
- AI providers: confirm whether they train on our data, and how long they keep prompts and outputs.

## 3. Risk levels

| Level | Example | Review |
|---|---|---|
| High | Holds customer data, or can act in our systems | every year |
| Medium | Holds internal data | every 2 years |
| Low | No access to our data | when the contract renews |

## 4. Outside AI agents

Outside agents connect to FloBrain only from hosts on the owner's allowlist. The owner approves the exact
list of tools. A changed tool list needs approval again. Every call is approved by its person.

## 5. Subprocessors

We keep a public list of subprocessors on our trust page and update it before a new one starts handling
customer data.

## 6. Ending a vendor

Remove its access, revoke keys and tokens, and get confirmation that our data was returned or deleted.
