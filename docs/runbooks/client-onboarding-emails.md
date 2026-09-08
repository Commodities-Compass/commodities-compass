# Client Onboarding — Email Templates

Three emails, FR and EN. They are sent by hand: there is no transactional mailer in this
codebase and no Auth0 Management API, so onboarding is a human sending three messages.

Companion to [entitlement-enforcement.md §2](./entitlement-enforcement.md#2-onboarding-a-new-client),
which is the technical half. Order: provision → **email 1** (access) → **email 2** (payment) →
the client pays → **email 3** only if a debit later fails.

---

## Rules that apply to all three

- **Tone.** The product is an editorial briefing sold to trading desks and cooperatives. Sober,
  short, no exclamation marks, no growth-marketing register. The email should read like the
  brief does.
- **Say the term once, in the payment email.** Twelve months initial, tacit renewal by
  twelve-month periods, thirty days' notice (CGV art. 7.1-7.3). Burying it is what turns a
  renewal into a dispute.
- **Prices are quoted HT.** That is what `/tarifs/` and CGV art. 8.1 publish. Services supplied
  to a client established outside the EU are not subject to French VAT; any tax due in the
  client's country is on top and at their charge — say it in those words, they are the published
  ones.
- **Link, do not paste.** CGV, tariffs and methodology are pages, not attachments — a pasted
  extract goes stale and an attachment is the version they will quote back at you.
- The no-`mailto:` rule from the landing page does **not** apply here: it exists to defeat
  harvesters crawling a public site, not to make a private email harder to answer.

### Variables

| | |
|---|---|
| `{prénom}` / `{first name}` | the person, not the company |
| `{offre}` | commercial name — Coop Essentiel, Coop Premium, Export Essentiel, Export Pro |
| `{montant}` | monthly EUR figure from [billing-and-collection.md §8 bis](../architecture/billing-and-collection.md#8-bis-the-live-catalogue) |
| `{lien}` | the Checkout URL from `create-checkout-link` — **expires after 24h** |
| `{lien portail}` | minted by hand, see email 3 |
| `{date}` | the failed debit's date |

### Two things to settle before the first send

1. **How the client obtains a first credential.** There is no Management API here: the Auth0
   user is created by hand in the dashboard. Whether Auth0 then emails a "set your password"
   invitation, or whether you send a password-change ticket, or whether the client signs in with
   Google — that is an Auth0 tenant setting nobody has written down. Email 1 has a marked slot
   for it. Fill it once, then it is constant.
2. **The sender.** `contact@` for commercial, `support@` for support (CGV art. 5.3). Whichever
   you choose must be a mailbox someone reads — a client replies to the address that wrote to
   them, not to the one in the signature.

---

## Email 1 — Access

**FR — objet : `Votre accès à Compass CC`**

> Bonjour {prénom},
>
> Votre accès à Compass CC est ouvert.
>
> **Se connecter** : https://app.com-compass.com
> **Identifiant** : {email}
> {⟨MÉCANIQUE DU MOT DE PASSE — à figer une fois pour toutes⟩}
>
> L'édition du jour est publiée chaque soir pour la séance du lendemain : le signal de position,
> la lecture de marché, la revue de presse, la météo des origines et le podcast quotidien. Votre
> offre {offre} donne accès à {périmètre en une ligne}.
>
> Deux points de méthode, que nous préférons dire d'emblée. Les lectures techniques que nous
> publions sont des **recommandations d'investissement** au sens du règlement (UE) n° 596/2014 :
> elles sont générales et strictement identiques pour tous les abonnés, et ne constituent ni un
> conseil personnalisé ni une garantie de résultat. Notre méthode, ce que signifient OPEN,
> MONITOR et HEDGE, et nos déclarations d'intérêts sont publiés ici :
> https://com-compass.com/methodologie/
>
> Une question sur le contenu : contact@com-compass.com. Un problème d'accès :
> support@com-compass.com.
>
> Bien à vous,
> {signature}

**EN — subject: `Your Compass CC access`**

> Dear {first name},
>
> Your Compass CC access is open.
>
> **Sign in**: https://app.com-compass.com
> **Username**: {email}
> {⟨PASSWORD MECHANICS — settle this once⟩}
>
> The daily edition is published each evening for the following session: the position signal,
> the market read, the press review, origin weather and the daily podcast. Your {offre} plan
> covers {scope in one line}.
>
> Two points of method, which we would rather state up front. The technical readings we publish
> are **investment recommendations** within the meaning of Regulation (EU) No 596/2014: they are
> general and strictly identical for every subscriber, and constitute neither personalised advice
> nor any guarantee of outcome. Our method, what OPEN, MONITOR and HEDGE mean, and our
> declarations of interest are published here: https://com-compass.com/en/methodology/
>
> Questions on the content: contact@com-compass.com. Access problems: support@com-compass.com.
>
> Kind regards,
> {signature}

---

## Email 2 — Payment

**FR — objet : `Compass CC — mise en place de votre abonnement`**

> Bonjour {prénom},
>
> Votre abonnement {offre} est prêt à être activé : **{montant} € HT par mois**.
>
> L'abonnement est souscrit pour une **durée initiale de douze mois**, reconduite tacitement par
> périodes de douze mois, sauf résiliation notifiée au plus tard trente jours avant l'échéance
> (articles 7.1 à 7.3 des conditions générales). Les prix sont exprimés hors taxes ; les
> prestations fournies à un client établi hors de l'Union européenne ne sont pas soumises à la
> TVA française, et toute taxe exigible dans votre pays s'ajoute au prix et reste à votre charge.
>
> **Enregistrer votre moyen de paiement** :
> {lien}
>
> Cette page est hébergée par Stripe, notre prestataire d'encaissement : vos données de carte ne
> transitent à aucun moment par nos serveurs. Votre banque vous demandera probablement de
> confirmer l'opération dans son application — c'est normal, nous le demandons volontairement.
>
> Ce lien reste valable vingt-quatre heures. Passé ce délai, écrivez-nous et nous vous en
> adressons un nouveau.
>
> Vous recevrez votre facture par e-mail après le premier prélèvement.
>
> Conditions générales : https://com-compass.com/cgv/
> Tarifs et conditions : https://com-compass.com/tarifs/
>
> Bien à vous,
> {signature}

**EN — subject: `Compass CC — setting up your subscription`**

> Dear {first name},
>
> Your {offre} subscription is ready to activate: **€{montant} per month, excluding tax**.
>
> The subscription runs for an **initial term of twelve months**, renewed tacitly for successive
> twelve-month periods unless notice is given at least thirty days before the term (articles 7.1
> to 7.3 of the general terms). Prices are quoted excluding tax; services supplied to a client
> established outside the European Union are not subject to French VAT, and any tax due in your
> country is added to the price and borne by you.
>
> **Register your payment method**:
> {lien}
>
> The page is hosted by Stripe, our payment processor: your card details never pass through our
> servers. Your bank will most likely ask you to confirm the operation in its app — that is
> expected, we request it deliberately.
>
> The link is valid for twenty-four hours. After that, write to us and we will send a new one.
>
> Your invoice follows by email after the first debit.
>
> General terms: https://com-compass.com/en/terms/
> Pricing and terms: https://com-compass.com/en/pricing/
>
> Kind regards,
> {signature}

---

## Email 3 — A debit failed

Sent when `cc-billing-watchdog` reports a failure, or `billing-status` shows `past_due`.
**Do not wait for the client to notice**: `past_due` deliberately keeps their access, so
nothing on their side looks wrong until Stripe gives up two to three weeks later.

Mint the portal URL by hand — the client cannot reach it themselves unless the banner is
showing (see the gap noted below):

```python
# with STRIPE_SECRET_KEY set to the live key
stripe.billing_portal.Session.create(
    customer="cus_…",                                   # from billing-status
    return_url="https://app.com-compass.com/dashboard",
).url
```

**FR — objet : `Compass CC — votre prélèvement du {date} n'a pas abouti`**

> Bonjour {prénom},
>
> Le prélèvement mensuel de {montant} € du {date} n'a pas été accepté par votre banque.
>
> **Votre accès n'est pas interrompu.** Une nouvelle présentation est automatique dans les jours
> qui viennent, et il n'y a rien à faire si elle aboutit.
>
> Si vous préférez ne pas attendre, vous pouvez mettre votre carte à jour ici :
> {lien portail}
>
> Les causes les plus fréquentes sont un plafond de paiement en ligne atteint, une carte arrivée
> à expiration, ou un blocage bancaire sur les paiements internationaux récurrents — ce dernier
> cas demande en général un simple appel à votre banque.
>
> Si la carte ne convient décidément pas, nous basculons votre abonnement sur virement : dites-le
> nous et nous vous adressons une facture.
>
> Bien à vous,
> {signature}

**EN — subject: `Compass CC — your {date} payment did not go through`**

> Dear {first name},
>
> The monthly debit of €{montant} on {date} was declined by your bank.
>
> **Your access is not interrupted.** The payment is automatically re-presented over the coming
> days, and there is nothing to do if it succeeds.
>
> If you would rather not wait, you can update your card here:
> {lien portail}
>
> The usual causes are an online payment ceiling reached, an expired card, or a bank block on
> recurring international payments — the last one is normally resolved by a phone call to your
> bank.
>
> If the card really will not work, we move your subscription to bank transfer: tell us and we
> will send an invoice.
>
> Kind regards,
> {signature}

---

## A gap these emails cannot paper over

The CGV define the **Espace Client** as "l'interface hébergée par le prestataire d'encaissement,
permettant au Client de mettre à jour son moyen de paiement, de consulter ses factures et de
gérer son Abonnement", and art. 7.3 says the client may terminate "directement depuis l'Espace
Client".

In the application today the Customer Portal is reachable **only through
`billing-banner.tsx`**, which renders only when `billingStatus ∈ {past_due, unpaid, canceled}`.
A client in good standing therefore has no way to reach it: they cannot see their invoices,
cannot update a card before it expires, and cannot exercise art. 7.3 as the contract describes
it. `POST /v1/billing/portal-session` exists and works — nothing links to it.

Until that is fixed, email 3 has to carry a hand-minted URL, and any other portal request is
answered by hand. It is a contractual gap, not only a UX one.
