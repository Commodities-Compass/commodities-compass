---
layout: '@/layouts/LegalLayout.astro'
title: "Privacy policy — Compass CC"
description: "Personal-data processing, legal bases, retention periods, sub-processors, transfers outside the EU and your rights."
eyebrow: "Legal information"
pathname: "/en/privacy/"
legalKey: "privacy"
locale: "en"
---
# Privacy Policy

*Last updated: 1 September 2026 — version 1.0*

---

## 1. Purpose and scope

COMMODITIES COMPASS SAS (hereinafter "**Compass**", "we") publishes an online subscription service providing daily analysis of the cocoa market.

This policy describes the processing of personal data for which **Compass acts as controller** within the meaning of Article 4(7) of Regulation (EU) 2016/679 ("GDPR"): account and access management, contract management, invoicing and collection, security, support, prospecting and audience measurement.

**It does not cover** data that our professional customers themselves upload to the service in the course of their own activity. For that data, **Compass acts as processor** on behalf of its customer, who remains the controller; the applicable regime is the data processing agreement annexed to the contract, not this policy.

This policy applies regardless of where the data subject is located. The GDPR applies to our processing because we are established in France (Article 3(1) GDPR), including where data subjects reside outside the European Union.

**Language.** This document is a translation provided for information purposes. **In the event of any discrepancy, the French version prevails.** It is made available in English to meet the requirement of intelligible information under Article 12(1) GDPR for our English-speaking users.

## 2. Controller and contact

**COMMODITIES COMPASS SAS**, *R.C.S. Lyon* 990 231 839, 8 bis allée du Baraillon, 69160 Tassin-la-Demi-Lune, France.

- Contact for any question or request to exercise rights: privacy@com-compass.com
- Post: to the registered office above, marked "Data protection"

## 3. Processing operations, purposes, legal bases and retention

| # | Processing | Data processed | Legal basis | Retention |
|---|---|---|---|---|
| 1 | **Accounts and access** — creation and management of user accounts, authentication, linkage to the customer, permissions | Email address, name, login identifier, linkage to customer, connection logs | Performance of the contract — Art. 6(1)(b); legitimate interest in securing access — Art. 6(1)(f) | Term of the contract, then **intermediate archiving for 5 years** from its end, with restricted access (limitation period for obligations between traders, Art. L110-4 French Commercial Code) |
| 2 | **Contract management** — conclusion, performance, renewal, termination, evidence of consent obtained at sign-up | Identity, contact details, subscription content, acceptance timestamps, evidence of the applicable regime (professional / non-professional) | Performance of the contract — Art. 6(1)(b) | Term of the contract, then **5 years** (Art. L110-4 French Commercial Code) |
| 3 | **Invoicing and accounting** | Customer and subscription identifiers, amounts, statuses, invoice references | Legal obligation — Art. 6(1)(c) | **10 years** from the close of the financial year (Art. L123-22 French Commercial Code) |
| 4 | **Evidence of the customer's location and status** (VAT place-of-supply obligations) | Billing address, country of the IP address at sign-up and at each renewal, country of issue of the payment method, local tax or registration number | Legal obligation — Art. 6(1)(c) | **10 years** from the transaction |
| 5 | **Raw payment notification archives** — retention of the payload of notifications received from our payment provider, solely as evidence in the event of a payment dispute | Payer's name, email address and country, amount, reference, timestamp | Legitimate interest in being able to defend against a dispute — Art. 6(1)(f) | **18 months** from the end of the subscription period covered by the relevant payment, then automatic purge |
| 6 | **Application technical logs** — detection and correction of faults | IP addresses, timestamps, authenticated user identifier, error context | Legitimate interest in the proper functioning of the service — Art. 6(1)(f) | **90 days** |
| 7 | **Security and access traceability logs** — detection of abnormal access and incidents | Identifier, timestamp, IP address, action performed | Legitimate interest in security — Art. 6(1)(f); Art. 32 GDPR | **6 months** |
| 8 | **Support and assistance** | Contact details, content of requests, exchanges | Performance of the contract — Art. 6(1)(b) | **2 years** from closure of the request |
| 9 | **International sanctions and asset-freeze screening** — verification of customers, directors and beneficial owners | Identity, corporate name, country, screening outcome | Legal obligation — Art. 6(1)(c) for mandatory measures; legitimate interest — Art. 6(1)(f) beyond | **5 years** from the last screening |
| 10 | **Prospecting and commercial relations** | Identity, role, business contact details, history of exchanges | Legitimate interest — Art. 6(1)(f), subject to the right to object | **3 years** from the person's last contact |
| 11 | **Audience measurement and trackers** | See § 8 | Consent — Art. 6(1)(a) and Art. 82 of French Law no. 78-17, except exempt trackers | Consent or refusal: **6 months** · Tracker lifetime: **13 months** maximum · Data collected: **25 months** maximum |

**We process no data falling within the special categories of Article 9 GDPR.**

**Mandatory provision.** The data in rows 1 to 4 is necessary for the conclusion and performance of the contract: without it, subscription is not possible.

## 4. Artificial intelligence and automated decision-making

The service uses algorithmic processing, including artificial intelligence systems, to produce analyses, indicators and market scenarios.

- This processing operates on market data and on data uploaded by the customer. **It takes no decision producing legal effects concerning users or similarly significantly affecting them** within the meaning of Article 22 GDPR.
- **We do not use users' personal data, nor data uploaded by our customers, to train or improve our models**, save with the customer's express and separate agreement, recorded in the contract. Absent such agreement, no such re-use takes place.
- Aggregated and anonymised statistics produced from use of the service do not allow re-identification and no longer constitute personal data.

## 5. Recipients and sub-processors

### 5.1 Processors acting on our instructions

| Provider | Contracting entity | Role | Data concerned | Location |
|---|---|---|---|---|
| **Google Cloud** | Google Cloud France, 8 rue de Londres, 75009 Paris — Google LLC group (United States) | Application and database hosting | All data covered by this policy, at infrastructure level | Storage at rest in the `europe-west9` region (Paris). Support access and maintenance operations possible from other countries, including the United States |
| **Auth0** | Okta, Inc., 100 First Street, San Francisco, California, United States | Authentication and identity management | Email address, name, login identifier, connection logs | Tenant data hosted in the Auth0 "EU" region (European Union). **The contract and the importer remain established in the United States** |
| **Sentry** | Functional Software, Inc. *dba* Sentry, 45 Fremont Street, 8th Floor, San Francisco, California, United States — EU representative: Sentry Software Netherlands B.V., Schiphol Boulevard 359, 1118 BJ Amsterdam, Netherlands | Application error monitoring | Email address and identifier of the authenticated user, technical error context | Ingestion and storage of error events in the European region (Frankfurt, Germany). **User accounts, access tokens, organisation settings and audit logs of the tool remain processed in the United States**, as does any data sent to the provider's support |

### 5.2 Recipient acting as an independent controller

**Stripe** — Stripe Payments Europe, Limited (Ireland), payment services being provided by Stripe Technology Europe, Limited, an electronic money institution authorised by the Central Bank of Ireland (reference C187865), and the Stripe group.

Stripe collects subscription payments. **No card data passes through our servers**: entry takes place on a page hosted by Stripe.

For payment and regulatory compliance data, **Stripe does not act on our instructions: it determines the purposes and means of the processing itself and acts as an independent controller**, under its own obligations as a payment institution. As a result:

- Stripe retains transaction data under its own rules, in principle for **at least five years** from the end of the business relationship or the last transaction;
- **we are not in a position to require Stripe to erase that data**; an erasure request relating to it must be addressed to Stripe.

Stripe's processing of data is governed by its own privacy policy.

### 5.3 Other recipients

Our accounting and legal advisers, our statutory auditors where applicable, and administrative or judicial authorities where required by law.

**We do not sell or rent your personal data.**

### 5.4 List kept up to date

The list of sub-processors is kept up to date and communicated to our professional customers; any addition or replacement is notified to them in advance, with a right to object, under the terms of the data processing agreement.

## 6. Transfers outside the European Union

Some of our providers belong to groups established in the United States, even where storage is located in Europe. Support, administration and maintenance access from a third country constitutes a transfer within the meaning of Chapter V GDPR.

| Provider | Third country concerned | Safeguard applied |
|---|---|---|
| Google Cloud / Google LLC | United States | Google LLC's certification under the **EU–U.S. Data Privacy Framework**, supplemented on a subsidiary basis by the **standard contractual clauses of Implementing Decision (EU) 2021/914** (modules 2 and 3) |
| Okta, Inc. (Auth0) | United States | Certification of Okta, Inc. and Auth0, LLC under the **EU–U.S. Data Privacy Framework**, and **standard contractual clauses 2021/914** (modules 2 and 3) |
| Functional Software, Inc. (Sentry) | United States | Certification under the **EU–U.S. Data Privacy Framework**, and **standard contractual clauses 2021/914** (modules 2 and 3) |
| Stripe group | United States and others | Stripe's own safeguards, in its capacity as an independent controller |

These transfers are the subject of a documented **transfer impact assessment** on our part, reviewed periodically, together with supplementary measures: encryption in transit and at rest, restriction and logging of remote access, minimisation of data sent to monitoring tools, and a policy for responding to requests from third-country authorities.

A copy of the safeguards in place may be obtained on request to privacy@com-compass.com.

**Customers established in Côte d'Ivoire and the ECOWAS area.** European hosting of the service constitutes, under Ivorian law, a transfer of data outside the ECOWAS area, subject to the prior authorisation regime of Law no. 2013-450 of 19 June 2013 on the protection of personal data. We carry out the corresponding formalities with the Ivorian Telecommunications Regulatory Authority (ARTCI) and make the related documentation available to our customers and to data subjects.

## 7. Security

We implement the appropriate technical and organisational measures required by Article 32 GDPR, in particular: encryption of data in transit and at rest, segregation of environments and tenants, named permission management on a least-privilege basis, strong authentication of administrative access, logging and monitoring, regular backups with tested restoration procedures, and periodic access reviews.

In the event of a personal data breach presenting a risk, we notify the French data protection authority (CNIL) within 72 hours and, where the risk is high, inform the data subjects. Where we act as processor, we inform the controller customer without delay and no later than the periods set out in the contract.

## 8. Trackers and cookies

The website places trackers strictly necessary for the operation of the service — session, authentication, security, load balancing. These trackers are exempt from consent under Article 82 of French Law no. 78-17 of 6 January 1978.

**We place no non-exempt audience measurement, advertising or third-party tracking trackers.** Should we do so, they would only be placed after obtaining your freely given, specific, informed and unambiguous consent, refusing being as simple as accepting, and this policy would be updated accordingly.

## 9. Your rights

You have the following rights, on the conditions and within the limits set by the GDPR:

- **access** to your data (Art. 15);
- **rectification** of inaccurate or incomplete data (Art. 16);
- **erasure**, where one of the grounds in Article 17 applies;
- **restriction** of processing (Art. 18);
- **portability** of the data you have provided to us, for processing based on contract or consent (Art. 20);
- **objection**, at any time, to processing based on our legitimate interest, and **without giving reasons** for direct marketing (Art. 21);
- **withdrawal of your consent** at any time, without affecting the lawfulness of processing carried out beforehand (Art. 7(3));
- **directives** concerning the fate of your data after your death (Art. 85 of French Law no. 78-17).

**How to exercise them.** Write to privacy@com-compass.com or to the registered office address. We may ask for proof of identity in the event of reasonable doubt. We respond within one month of receipt, extendable by two months for complex requests, in which case we will inform you.

**If you are a user of an account opened by a professional customer**, address your request to that customer, who is the controller for data uploaded to the service; we assist them in handling your request.

**Complaints.** You may lodge a complaint with the French data protection authority — Commission nationale de l'informatique et des libertés, 3 place de Fontenoy, TSA 80715, 75334 Paris Cedex 07, France — `www.cnil.fr`. If you reside outside the European Union, you may also refer the matter to the data protection authority of your country of residence where one exists; in Côte d'Ivoire, the Ivorian Telecommunications Regulatory Authority (ARTCI).

## 10. Changes to this policy

We may amend this policy to reflect legal, technical or organisational developments. Any material change is brought to users' attention by appropriate means, and the update date shown at the top of the document is revised. Previous versions are retained and available on request.
