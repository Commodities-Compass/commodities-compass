# Client Onboarding — Email Templates

Two emails, FR and EN. Sent by hand: there is no transactional mailer in this codebase and no
Auth0 Management API, so onboarding is a human sending one message, then a second one only if a
debit later fails.

Companion to [entitlement-enforcement.md §2](./entitlement-enforcement.md#2-onboarding-a-new-client),
which is the technical half. Order: create the Auth0 user → provision the tenant → mint the
Checkout link → **email 1** (welcome, credentials, payment) → **email 2** only if a debit fails.

An HTML version of email 1, ready to paste into Gmail, is at
[`client-welcome-email.html`](./client-welcome-email.html).

---

## Rules

- **Tone.** The product is an editorial briefing sold to trading desks and cooperatives. Sober,
  short, no exclamation marks, no growth-marketing register. It should read like the brief does.
- **One email, not two.** Access and payment arrive together: a client who receives credentials
  and then waits for a payment link assumes something is missing.
- **Link, do not paste.** CGV and tariffs are pages, not attachments — a pasted extract goes
  stale and an attachment is the version they will quote back at you.
- The no-`mailto:` rule from the landing page does **not** apply here: it exists to defeat
  harvesters crawling a public site, not to make a private email harder to answer.

### Variables

| | |
|---|---|
| `{prénom}` / `{first name}` | the person, not the company |
| `{offre}` | commercial name — Coop Essentiel, Coop Premium, Export Essentiel, Export Pro |
| `{montant}` | monthly EUR figure from [billing-and-collection.md §8 bis](../architecture/billing-and-collection.md#8-bis-the-live-catalogue) |
| `{lien}` | the Checkout URL from `create-checkout-link` — **expires after 24h** |
| `{lien portail}` | minted by hand, see email 2 |
| `{date}` | the failed debit's date |

### The sender is `support@com-compass.com`

Both go out from `support@`, the address CGV art. 5.3 already names as the support channel. A
client replies to whatever wrote to them, so this is also where the answers land.

⚠️ **One exception that is contractual, not stylistic.** CGV art. 7.3 says a termination may be
notified "par tout écrit adressé à **contact@com-compass.com**". A client who terminates by
replying to `support@` has still notified you — a written notice is valid wherever it lands — but
the thirty-day clock starts on the date it was *sent*, not the date someone forwards it. So a
termination arriving in `support@` must be acknowledged and moved the same day. Do not answer it
with "please write to contact@": that is not a condition the contract imposes.

### Credentials — pick one mechanic and keep it

**A. A password we set, sent in the email.** What the templates below assume. Simple, works with
no Auth0 configuration — and it puts a working credential in cleartext in a mailbox that keeps it
forever, including the client's mail provider, their backups, and anyone later given access to
that inbox. Mitigate by inviting the change on first sign-in, as the template does.

**B. An Auth0 "set your password" link.** Create the user without a password and have Auth0 send
the invitation, or send a password-change ticket from the dashboard. Nothing reusable transits by
email, and the client chooses their own secret from the start. Costs one Auth0 tenant setting.

B is the better mechanic. A is what ships if nobody configures B. The template carries A with the
line to swap marked, so switching later is one edit.

### ⚠️ TTC vs HT — unresolved contradiction

These templates say **TTC** (tax included), on instruction. The published pages say the opposite,
twice:

- `/tarifs/`: "En euros (EUR), **hors taxes**" and "Les prix sont exprimés hors taxes. **Toute
  taxe exigible dans le pays du client — notamment la taxe sur la valeur ajoutée locale —
  s'ajoute au prix et reste à sa charge.**"
- CGV art. 8.1: "exprimés en euros, **hors taxes**".

The second sentence is the binding one: it authorises invoicing *above* the advertised figure. So
today a client can be sent an email saying TTC and read a contract saying HT-plus-local-tax. For
the actual clientele it is moot — a B2B service supplied outside the EU is out of scope of French
VAT (CGI art. 259-1), so HT and TTC name the same number — but it stops being moot for a French
or EU client. **The pages need to be brought in line with the commercial intent; that is a lawyer
question, not a code one.** Stripe itself is unaffected: `tax_behavior` has no effect while Stripe
Tax is off, and it is `exclusive` on all four live prices — which is the safe setting if a French
client ever appears.

---

## Email 1 — Welcome, access and payment

**FR — objet : `Bienvenue sur Compass CC — votre accès et votre abonnement`**

> Bonjour {prénom},
>
> Votre espace Compass CC est prêt. Voici de quoi vous connecter et activer votre abonnement.
>
> **Votre accès**
> Adresse : https://app.com-compass.com
> Identifiant : {email}
> Mot de passe provisoire : `{mot de passe}`
>
> Nous vous invitons à le remplacer dès votre première connexion.
>
> **Ce que vous y trouverez**
> Chaque soir, l'édition du lendemain est publiée : le signal de position du jour, la lecture de
> marché, la revue de presse, la météo des zones de production, et le podcast quotidien à écouter
> en dix minutes. Votre offre {offre} donne accès à {périmètre en une ligne}.
>
> **Activer votre abonnement — {montant} € TTC par mois**
> {lien}
>
> La page est hébergée par Stripe, notre prestataire d'encaissement : vos données de carte ne
> transitent à aucun moment par nos serveurs. Votre banque vous demandera probablement de
> confirmer l'opération dans son application — c'est normal, nous le demandons volontairement.
> Le lien reste valable vingt-quatre heures ; passé ce délai, répondez-nous et nous vous en
> adressons un nouveau. Votre facture suit par e-mail après le premier prélèvement.
>
> Conditions générales : https://com-compass.com/cgv/ — Tarifs : https://com-compass.com/tarifs/
>
> Bien à vous,
> {signature}

**EN — subject: `Welcome to Compass CC — your access and subscription`**

> Dear {first name},
>
> Your Compass CC workspace is ready. Here is how to sign in and activate your subscription.
>
> **Your access**
> Address: https://app.com-compass.com
> Username: {email}
> Temporary password: `{password}`
>
> We recommend replacing it on your first sign-in.
>
> **What you will find there**
> Each evening, the following day's edition is published: the day's position signal, the market
> read, the press review, the weather across the producing regions, and the daily podcast, ten
> minutes long. Your {offre} plan covers {scope in one line}.
>
> **Activate your subscription — €{montant} per month, tax included**
> {lien}
>
> The page is hosted by Stripe, our payment processor: your card details never pass through our
> servers. Your bank will most likely ask you to confirm the operation in its app — that is
> expected, we request it deliberately. The link is valid for twenty-four hours; after that,
> reply to us and we will send a new one. Your invoice follows by email after the first debit.
>
> Terms: https://com-compass.com/en/terms/ — Pricing: https://com-compass.com/en/pricing/
>
> Kind regards,
> {signature}

---

## Email 2 — A debit failed

Sent when `cc-billing-watchdog` reports a failure, or `billing-status` shows `past_due`.
**Do not wait for the client to notice**: `past_due` deliberately keeps their access, so nothing
on their side looks wrong until Stripe gives up two to three weeks later.

Mint the portal URL by hand — the client cannot reach it themselves unless the banner is showing
(see the gap noted below):

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

Until that is fixed, email 2 has to carry a hand-minted URL, and any other portal request is
answered by hand. It is a contractual gap, not only a UX one.
