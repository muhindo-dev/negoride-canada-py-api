"""Seed content for the v1.0 legal documents (spec §12).

Each entry in ``DOCUMENTS`` describes one legal document type with its
audience and bilingual (English / Canadian French) title, plain-language
summary box and full Markdown body.

Bodies and summaries are Jinja2 templates. They only use simple
``{{ var }}`` placeholders (never ``{% %}`` blocks) so that figures such as
fees, time windows, retention periods and commission rates are always
rendered from live app settings and can never drift from the engines that
enforce them. Allowed placeholders:

    company_legal_name, support_email, website, company_address,
    tracking_retention_days, recording_retention_days,
    recording_hold_after_case_days, min_driver_age, min_vehicle_year,
    recheck_months, commission_pct, bgc_fee, certn_dispute_contact,
    free_window_min, cancel_fee, cancel_fee_pct_cap, after_arrival_fee,
    wait_free_min, wait_rate_per_min, wait_window_min, noshow_fee,
    driver_credit, driver_no_show_grace_min, rideshare_refund_full_h,
    rideshare_refund_half_h, rideshare_refund_half_pct,
    strikes_warn_after, strikes_window_days, strikes_suspend_after,
    strikes_suspend_days

All documents are DRAFTS prepared for review by legal counsel before
launch. Clauses that need specific legal review are flagged inline with
``**[REVIEW WITH COUNSEL]**`` (French: ``**[À RÉVISER PAR UN AVOCAT]**``).
"""

VERSION = '1.0'

DOCUMENTS = [
    # ------------------------------------------------------------------
    # 1. Terms & Conditions
    # ------------------------------------------------------------------
    {
        'type': 'terms',
        'audience': 'all',
        'title': {
            'en': 'Terms & Conditions',
            'fr': 'Conditions d’utilisation',
        },
        'summary': {
            'en': """- NegoRide is a technology platform that connects riders with independent drivers; drivers are not our employees.
- For Car Hire, you and the driver agree on a price in the app before the ride. Once agreed, that price is final unless you both change it in the app.
- Your card is authorized (a temporary hold) before the driver heads to you and is charged only when the trip is completed.
- Cancellation fees, no-show fees and refunds follow our Cancellation & Refund Policy.
- You must be 18 or older and follow our Community Guidelines. Breaking the rules can lead to suspension or a ban, which you can appeal.
- In an emergency, always call 911. NegoRide is not an emergency service.
""",
            'fr': """- NegoRide est une plateforme technologique qui met en relation des passagers et des chauffeurs indépendants; les chauffeurs ne sont pas nos employés.
- Pour la Location avec chauffeur, vous et le chauffeur convenez d’un prix dans l’application avant la course. Une fois accepté, ce prix est définitif, sauf si vous le modifiez tous les deux dans l’application.
- Votre carte fait l’objet d’une autorisation (retenue temporaire) avant que le chauffeur se mette en route, et elle n’est débitée qu’à la fin de la course.
- Les frais d’annulation, les frais de non-présentation et les remboursements sont régis par notre Politique d’annulation et de remboursement.
- Vous devez avoir 18 ans ou plus et respecter nos Lignes directrices de la communauté. Tout manquement peut entraîner une suspension ou un bannissement, que vous pouvez contester.
- En cas d’urgence, composez toujours le 911. NegoRide n’est pas un service d’urgence.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

These Terms & Conditions (the "Terms") form a binding agreement between you and {{ company_legal_name }} ("NegoRide", "we", "us" or "our"), located at {{ company_address }}. They govern your access to and use of the NegoRide mobile applications, the website at {{ website }}, and all related services (together, the "Platform"). By creating an account, tapping "I agree", or using the Platform, you confirm that you have read, understood and accepted these Terms, our Privacy Policy, our Community Guidelines, our Cancellation & Refund Policy, our Safety Policy and our Audio Recording Notice, each of which forms part of these Terms. If you do not agree, do not use the Platform.

## 1. Who we are and what we do

NegoRide is a technology platform. We enable people who want transportation or delivery services ("Riders" or "Customers") to connect with independent third-party drivers ("Drivers") who offer those services. Our services include:

- **Car Hire** — on-demand rides where the Rider and the Driver negotiate and agree on a price in the app before the ride begins;
- **Rideshare** — scheduled intercity or commuter journeys published by Drivers, on which Riders book individual seats;
- **Courier, Movers and Airport Pickup** — delivery, moving and airport transfer services offered by Drivers through the Platform.

**NegoRide does not provide transportation services and is not a transportation carrier.** Drivers are independent contractors who decide when, where and whether to offer services. Nothing in these Terms creates an employment, agency, partnership or joint-venture relationship between NegoRide and any Driver or Rider. **[REVIEW WITH COUNSEL]** — confirm characterization against provincial and municipal vehicle-for-hire regulations (e.g., licensing as a transportation network company where required).

## 2. Eligibility and your account

You must be at least 18 years old and able to enter into a binding contract to hold an account. You agree to:

- provide accurate, current and complete information, including a mobile phone number that we verify by one-time code;
- keep your password and devices secure and not share your account with anyone;
- notify us promptly at {{ support_email }} if you suspect unauthorized use of your account.

You are responsible for all activity that occurs under your account. Drivers must also meet the additional requirements in the Driver Agreement, including document verification and a background check.

## 3. How Car Hire works — negotiated pricing

The "Nego" in NegoRide stands for negotiation. When you request a Car Hire ride, you may propose a price, and Drivers may accept, decline or make a counter-offer. Either party may make offers until one party accepts.

- **The agreed price is binding.** Once both parties accept a price in the app, that price is the fare for the trip as described (pickup, destination and any stops agreed at the time).
- **Changes must be made in the app.** The fare may only change if both parties agree to a new price through the app — for example, if the Rider adds a stop or changes the destination. Drivers may not demand a different price in person.
- **No off-app deals.** Arranging trips, payments or cash deals outside the Platform with someone you met through NegoRide is prohibited and removes the protections of these Terms, including safety features, insurance coverage arranged for trips booked in the app, and our dispute resolution.
- Applicable taxes, tolls, waiting-time charges and fees described in the Cancellation & Refund Policy may be added as shown in the app.

## 4. Rideshare seat bookings

Drivers publish scheduled journeys with a departure time, route, price per seat and number of seats. When you book a seat, you agree to be at the pickup point on time and to follow the Driver's reasonable instructions consistent with our Community Guidelines. Drivers set their own seat prices within limits we may establish. Cancellations and refunds for seats follow the Cancellation & Refund Policy.

## 5. Payments

All prices are in Canadian dollars (CAD). Payments are processed by our payment processor, Stripe. We never see or store your full card number.

- **Authorization before the trip.** For Car Hire, after a price is agreed we place a temporary authorization (a "hold") on your payment method before the Driver heads to your pickup location. If authorization fails, the trip will not proceed.
- **Capture at completion.** The authorized amount (adjusted for any in-app changes, waiting time or applicable fees) is charged when the trip is completed. Unused portions of a hold are released.
- **Rideshare seats** are charged at the time of booking unless the app states otherwise.
- **Service fee / commission.** NegoRide earns a commission from each fare, deducted from the Driver's earnings as described in the Driver Agreement.
- **Receipts** are available in the app and sent by email.

You authorize us and Stripe to charge your payment method for all amounts owing under these Terms. If a charge fails, we may suspend your account until the balance is paid.

## 6. Cancellations, no-shows and refunds

Cancellation fees, waiting-time charges, no-show fees, ride credits and refunds are governed by our Cancellation & Refund Policy, which forms part of these Terms. The amounts in that policy are shown in the app and may change from time to time; the version in force when you confirm your trip applies to that trip.

## 7. Your conduct

You agree to follow our Community Guidelines at all times, including rules on respect, non-discrimination, harassment, weapons, drugs and alcohol, seat belts, child car seats, service animals, vehicle cleanliness and fair negotiation. You must not:

- use the Platform for any unlawful purpose or to transport illegal goods;
- create multiple accounts or impersonate anyone;
- interfere with, reverse-engineer, scrape or attempt to gain unauthorized access to the Platform;
- manipulate ratings, promotions, referral credits or the negotiation system;
- misuse the SOS or safety features.

You are responsible for any damage you cause to a Driver's vehicle beyond normal wear, including cleaning fees described in the Cancellation & Refund Policy and Community Guidelines.

## 8. Safety features

The Platform includes safety features such as an SOS button connected to our 24/7 safety team, a 911 shortcut, a ride PIN, live trip sharing with trusted contacts, route-deviation checks and optional in-trip audio recording. These features are tools to help you; they do not guarantee your safety. **NegoRide is not an emergency service. In an emergency, always call 911.** See our Safety Policy and Audio Recording Notice for details.

## 9. Ratings and reviews

After each trip, Riders and Drivers may rate each other. Ratings must be honest and based on the trip experience. We may remove ratings or comments that are discriminatory, abusive, retaliatory or unrelated to the trip. Low ratings may affect access to the Platform, as described in the Community Guidelines and Driver Agreement.

## 10. Suspension, deactivation and appeals

We may warn you, temporarily suspend, deactivate or permanently ban your account if we reasonably believe you have breached these Terms, our policies or the law, or if necessary to protect the safety of users or the public. In urgent safety matters, we may act immediately and investigate afterwards. Where appropriate, we will tell you the reason. You may appeal any decision by opening a support ticket in the app or by writing to {{ support_email }}. A different member of our team will review your appeal. You may close your account at any time from the app settings.

## 11. Third-party services

The Platform relies on third-party services, including Stripe (payments), Twilio (phone verification), OneSignal (notifications), Google (maps) and Certn (Driver background checks). Your use of those services may also be subject to their terms. We are not responsible for third-party services we do not control.

## 12. Intellectual property

The Platform, including its software, design, trademarks and content, belongs to NegoRide or its licensors. We grant you a limited, revocable, non-exclusive, non-transferable licence to use the app for its intended personal purpose. You grant us a licence to use content you submit (such as ratings and comments) to operate and improve the Platform.

## 13. Disclaimers

To the maximum extent permitted by law, the Platform is provided "as is" and "as available". We do not guarantee that the Platform will be uninterrupted or error-free, that a Driver or trip will be available, or the conduct of any user. Nothing in these Terms limits rights you have under applicable consumer protection legislation that cannot be waived by contract. **[REVIEW WITH COUNSEL]** — Québec Consumer Protection Act and other provincial consumer statutes may restrict disclaimers.

## 14. Limitation of liability

To the maximum extent permitted by law, NegoRide will not be liable for indirect, incidental, special, consequential or punitive damages, or for loss of profits, data or goodwill, arising from your use of the Platform. Our total liability for any claim relating to the Platform is limited to the greater of the amount you paid through the Platform in the three months before the claim and one hundred Canadian dollars. These limits do not apply to liability that cannot be limited by law, including for gross negligence, intentional fault, or bodily injury where such limitation is prohibited. **[REVIEW WITH COUNSEL]**

## 15. Indemnity

To the extent permitted by law, you agree to indemnify and hold NegoRide harmless from claims, losses and expenses (including reasonable legal fees) arising from your breach of these Terms or of the law, or from your misuse of the Platform. **[REVIEW WITH COUNSEL]** — enforceability against consumers, particularly in Québec.

## 16. Disputes

Please contact us first at {{ support_email }} so we can try to resolve any concern informally. Fare and charge disputes should be raised within 72 hours of the trip. If we cannot resolve a dispute, it may be brought before the courts described in section 18. Nothing in these Terms prevents you from bringing a claim in small claims court or from filing a complaint with a consumer protection authority. **[REVIEW WITH COUNSEL]** — consider whether any arbitration clause is desirable and enforceable (e.g., not permitted against Québec consumers).

## 17. Changes to these Terms

We may update these Terms from time to time. If we make material changes, we will notify you in the app or by email before they take effect and, where required, ask you to accept the new version. The version number and history are available in the app. If you continue to use the Platform after changes take effect, you accept the updated Terms.

## 18. Governing law

These Terms are governed by the laws of the Province of Ontario and the federal laws of Canada applicable therein, without regard to conflict-of-law rules. If you are a consumer residing in another province or territory, you may also benefit from mandatory protections of the laws of your province, and you may bring proceedings in the courts of your province where the law so allows. **[REVIEW WITH COUNSEL]**

## 19. Language

These Terms are available in English and French. Both versions are equally authoritative. The parties have expressly required that these Terms and all related documents be drawn up in both English and French.

## 20. General

If any provision of these Terms is found unenforceable, the rest remains in effect. Our failure to enforce a provision is not a waiver. You may not assign these Terms without our consent; we may assign them in connection with a merger, acquisition or sale of assets. These Terms, with the policies referred to in them, are the entire agreement between you and us regarding the Platform.

## 21. Contact us

{{ company_legal_name }}
{{ company_address }}
Email: {{ support_email }}
Website: {{ website }}
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

Les présentes Conditions d’utilisation (les « Conditions ») constituent une entente contraignante entre vous et {{ company_legal_name }} (« NegoRide », « nous » ou « notre »), situé au {{ company_address }}. Elles régissent votre accès aux applications mobiles NegoRide, au site Web {{ website }} et à tous les services connexes (collectivement, la « Plateforme »), ainsi que votre utilisation de ceux-ci. En créant un compte, en touchant « J’accepte » ou en utilisant la Plateforme, vous confirmez avoir lu, compris et accepté les présentes Conditions, notre Politique de confidentialité, nos Lignes directrices de la communauté, notre Politique d’annulation et de remboursement, notre Politique de sécurité et notre Avis sur l’enregistrement audio, qui font tous partie intégrante des présentes Conditions. Si vous ne les acceptez pas, n’utilisez pas la Plateforme.

## 1. Qui nous sommes et ce que nous faisons

NegoRide est une plateforme technologique. Elle permet aux personnes qui ont besoin de transport ou de livraison (les « Passagers » ou « Clients ») d’entrer en contact avec des chauffeurs tiers indépendants (les « Chauffeurs ») qui offrent ces services. Nos services comprennent :

- **Location avec chauffeur** — des courses sur demande pour lesquelles le Passager et le Chauffeur négocient et conviennent d’un prix dans l’application avant le début de la course;
- **Covoiturage** — des trajets interurbains ou de navettage planifiés, publiés par des Chauffeurs, sur lesquels les Passagers réservent des places;
- **Messagerie, Déménagement et Navette aéroport** — des services de livraison, de déménagement et de transfert vers l’aéroport offerts par des Chauffeurs au moyen de la Plateforme.

**NegoRide ne fournit pas de services de transport et n’est pas un transporteur.** Les Chauffeurs sont des entrepreneurs indépendants qui décident quand, où et s’ils offrent leurs services. Rien dans les présentes Conditions ne crée de relation d’emploi, de mandat, de société ou de coentreprise entre NegoRide et un Chauffeur ou un Passager. **[À RÉVISER PAR UN AVOCAT]** — valider cette qualification au regard de la réglementation provinciale et municipale sur le transport rémunéré de personnes (p. ex. l’obligation d’être autorisé comme répartiteur ou entreprise de réseau de transport, le cas échéant).

## 2. Admissibilité et compte

Vous devez avoir au moins 18 ans et être capable de conclure un contrat contraignant pour détenir un compte. Vous vous engagez à :

- fournir des renseignements exacts, à jour et complets, y compris un numéro de téléphone mobile que nous vérifions au moyen d’un code à usage unique;
- protéger votre mot de passe et vos appareils et ne partager votre compte avec personne;
- nous aviser rapidement à {{ support_email }} si vous soupçonnez une utilisation non autorisée de votre compte.

Vous êtes responsable de toute activité effectuée au moyen de votre compte. Les Chauffeurs doivent aussi satisfaire aux exigences supplémentaires du Contrat du chauffeur, notamment la vérification des documents et la vérification des antécédents.

## 3. Fonctionnement de la Location avec chauffeur — prix négocié

Le « Nego » de NegoRide signifie négociation. Lorsque vous demandez une course en Location avec chauffeur, vous pouvez proposer un prix, et les Chauffeurs peuvent l’accepter, le refuser ou faire une contre-offre. Chaque partie peut faire des offres jusqu’à ce que l’une d’elles accepte.

- **Le prix convenu est contraignant.** Dès que les deux parties acceptent un prix dans l’application, ce prix constitue le tarif de la course telle qu’elle a été décrite (point de prise en charge, destination et arrêts convenus à ce moment).
- **Toute modification doit se faire dans l’application.** Le tarif ne peut changer que si les deux parties acceptent un nouveau prix dans l’application — par exemple, si le Passager ajoute un arrêt ou change de destination. Le Chauffeur ne peut pas exiger un autre prix en personne.
- **Aucune entente hors application.** Il est interdit d’organiser des courses, des paiements ou des ententes en argent comptant en dehors de la Plateforme avec une personne rencontrée par NegoRide. Une telle entente vous prive des protections des présentes Conditions, notamment des fonctions de sécurité, de la couverture d’assurance prévue pour les courses réservées dans l’application et de notre processus de règlement des différends.
- Les taxes applicables, les péages, les frais d’attente et les frais décrits dans la Politique d’annulation et de remboursement peuvent s’ajouter, comme indiqué dans l’application.

## 4. Réservation de places en Covoiturage

Les Chauffeurs publient des trajets planifiés comportant une heure de départ, un itinéraire, un prix par place et un nombre de places. Lorsque vous réservez une place, vous vous engagez à être au point de prise en charge à l’heure prévue et à suivre les consignes raisonnables du Chauffeur, conformément à nos Lignes directrices de la communauté. Les Chauffeurs fixent le prix de leurs places dans les limites que nous pouvons établir. Les annulations et remboursements de places sont régis par la Politique d’annulation et de remboursement.

## 5. Paiements

Tous les prix sont en dollars canadiens (CAD). Les paiements sont traités par notre fournisseur de services de paiement, Stripe. Nous ne voyons ni ne conservons jamais le numéro complet de votre carte.

- **Autorisation avant la course.** En Location avec chauffeur, une fois le prix convenu, nous plaçons une autorisation temporaire (une « retenue ») sur votre mode de paiement avant que le Chauffeur se rende au point de prise en charge. Si l’autorisation échoue, la course n’a pas lieu.
- **Prélèvement à la fin de la course.** Le montant autorisé (ajusté selon les modifications faites dans l’application, le temps d’attente ou les frais applicables) est débité à la fin de la course. La partie inutilisée d’une retenue est libérée.
- **Les places en Covoiturage** sont débitées au moment de la réservation, sauf indication contraire dans l’application.
- **Frais de service / commission.** NegoRide perçoit une commission sur chaque tarif, déduite des gains du Chauffeur comme le prévoit le Contrat du chauffeur.
- **Les reçus** sont accessibles dans l’application et envoyés par courriel.

Vous nous autorisez, ainsi que Stripe, à débiter votre mode de paiement de toutes les sommes dues en vertu des présentes Conditions. Si un paiement échoue, nous pouvons suspendre votre compte jusqu’au règlement du solde.

## 6. Annulations, non-présentations et remboursements

Les frais d’annulation, les frais d’attente, les frais de non-présentation, les crédits de course et les remboursements sont régis par notre Politique d’annulation et de remboursement, qui fait partie des présentes Conditions. Les montants qui y figurent sont affichés dans l’application et peuvent changer de temps à autre; la version en vigueur au moment où vous confirmez votre course s’applique à celle-ci.

## 7. Votre conduite

Vous vous engagez à respecter en tout temps nos Lignes directrices de la communauté, y compris les règles sur le respect, la non-discrimination, le harcèlement, les armes, les drogues et l’alcool, la ceinture de sécurité, les sièges d’auto pour enfants, les animaux d’assistance, la propreté des véhicules et la négociation équitable. Il vous est interdit :

- d’utiliser la Plateforme à des fins illégales ou pour transporter des marchandises illégales;
- de créer plusieurs comptes ou d’usurper l’identité d’une autre personne;
- de perturber la Plateforme, d’en faire l’ingénierie inverse, d’en extraire des données de façon automatisée ou de tenter d’y accéder sans autorisation;
- de manipuler les évaluations, les promotions, les crédits de parrainage ou le système de négociation;
- d’utiliser abusivement le bouton SOS ou les fonctions de sécurité.

Vous êtes responsable des dommages que vous causez au véhicule d’un Chauffeur au-delà de l’usure normale, y compris les frais de nettoyage décrits dans la Politique d’annulation et de remboursement et les Lignes directrices de la communauté.

## 8. Fonctions de sécurité

La Plateforme comprend des fonctions de sécurité, comme un bouton SOS relié à notre équipe de sécurité disponible 24 heures sur 24, 7 jours sur 7, un raccourci vers le 911, un NIP de course, le partage du trajet en temps réel avec des contacts de confiance, la détection des écarts d’itinéraire et l’enregistrement audio facultatif pendant la course. Ces fonctions sont des outils pour vous aider; elles ne garantissent pas votre sécurité. **NegoRide n’est pas un service d’urgence. En cas d’urgence, composez toujours le 911.** Pour en savoir plus, consultez notre Politique de sécurité et notre Avis sur l’enregistrement audio.

## 9. Évaluations et commentaires

Après chaque course, les Passagers et les Chauffeurs peuvent s’évaluer mutuellement. Les évaluations doivent être honnêtes et fondées sur l’expérience de la course. Nous pouvons retirer les évaluations ou commentaires discriminatoires, injurieux, faits par représailles ou sans lien avec la course. De faibles évaluations peuvent limiter l’accès à la Plateforme, comme le prévoient les Lignes directrices de la communauté et le Contrat du chauffeur.

## 10. Suspension, désactivation et contestation

Nous pouvons vous donner un avertissement, suspendre temporairement, désactiver ou bannir définitivement votre compte si nous avons des motifs raisonnables de croire que vous avez enfreint les présentes Conditions, nos politiques ou la loi, ou si cela est nécessaire pour protéger la sécurité des utilisateurs ou du public. En matière de sécurité urgente, nous pouvons agir immédiatement et enquêter ensuite. Lorsqu’il y a lieu, nous vous en indiquerons le motif. Vous pouvez contester toute décision en ouvrant un billet de soutien dans l’application ou en écrivant à {{ support_email }}. Un autre membre de notre équipe examinera votre contestation. Vous pouvez fermer votre compte en tout temps à partir des paramètres de l’application.

## 11. Services de tiers

La Plateforme repose sur des services de tiers, notamment Stripe (paiements), Twilio (vérification du numéro de téléphone), OneSignal (notifications), Google (cartes) et Certn (vérification des antécédents des Chauffeurs). Votre utilisation de ces services peut aussi être assujettie à leurs propres conditions. Nous ne sommes pas responsables des services de tiers que nous ne contrôlons pas.

## 12. Propriété intellectuelle

La Plateforme, y compris ses logiciels, sa conception, ses marques de commerce et son contenu, appartient à NegoRide ou à ses concédants de licence. Nous vous accordons une licence limitée, révocable, non exclusive et non transférable vous permettant d’utiliser l’application à des fins personnelles conformes à sa destination. Vous nous accordez une licence d’utilisation du contenu que vous soumettez (comme les évaluations et commentaires) afin d’exploiter et d’améliorer la Plateforme.

## 13. Exclusions de garantie

Dans toute la mesure permise par la loi, la Plateforme est fournie « telle quelle » et « selon sa disponibilité ». Nous ne garantissons pas que la Plateforme fonctionnera sans interruption ni erreur, qu’un Chauffeur ou une course sera disponible, ni la conduite d’un utilisateur. Rien dans les présentes Conditions ne limite les droits que vous confère la législation sur la protection du consommateur et auxquels il ne peut être dérogé par contrat. **[À RÉVISER PAR UN AVOCAT]** — la Loi sur la protection du consommateur du Québec et les autres lois provinciales peuvent restreindre ces exclusions.

## 14. Limitation de responsabilité

Dans toute la mesure permise par la loi, NegoRide ne sera pas responsable des dommages indirects, accessoires, spéciaux, consécutifs ou punitifs, ni de la perte de profits, de données ou d’achalandage, découlant de votre utilisation de la Plateforme. Notre responsabilité totale à l’égard de toute réclamation liée à la Plateforme est limitée au plus élevé des montants suivants : la somme que vous avez payée au moyen de la Plateforme au cours des trois mois précédant la réclamation, ou cent dollars canadiens. Ces limites ne s’appliquent pas à la responsabilité qui ne peut être limitée par la loi, notamment en cas de faute lourde, de faute intentionnelle ou de préjudice corporel lorsque la loi l’interdit. **[À RÉVISER PAR UN AVOCAT]**

## 15. Indemnisation

Dans la mesure permise par la loi, vous acceptez d’indemniser NegoRide et de la tenir indemne de toute réclamation, perte ou dépense (y compris les frais juridiques raisonnables) découlant de votre violation des présentes Conditions ou de la loi, ou de votre mauvaise utilisation de la Plateforme. **[À RÉVISER PAR UN AVOCAT]** — opposabilité aux consommateurs, particulièrement au Québec.

## 16. Différends

Veuillez d’abord communiquer avec nous à {{ support_email }} afin que nous tentions de régler votre préoccupation à l’amiable. Toute contestation d’un tarif ou d’un débit doit être soumise dans les 72 heures suivant la course. Si nous ne parvenons pas à régler un différend, celui-ci peut être porté devant les tribunaux mentionnés à l’article 18. Rien dans les présentes Conditions ne vous empêche d’intenter un recours devant la division des petites créances ou de déposer une plainte auprès d’un organisme de protection du consommateur. **[À RÉVISER PAR UN AVOCAT]** — évaluer l’opportunité et la validité d’une clause d’arbitrage (p. ex. interdite à l’égard des consommateurs québécois).

## 17. Modification des présentes Conditions

Nous pouvons mettre à jour les présentes Conditions de temps à autre. En cas de modification importante, nous vous en aviserons dans l’application ou par courriel avant son entrée en vigueur et, lorsque la loi l’exige, nous vous demanderons d’accepter la nouvelle version. Le numéro de version et l’historique sont accessibles dans l’application. Si vous continuez d’utiliser la Plateforme après l’entrée en vigueur des modifications, vous acceptez les Conditions mises à jour.

## 18. Droit applicable

Les présentes Conditions sont régies par les lois de la province d’Ontario et les lois fédérales du Canada qui s’y appliquent, sans égard aux règles de conflit de lois. Si vous êtes un consommateur résidant dans une autre province ou un territoire, vous pouvez aussi bénéficier des protections impératives des lois de votre province et intenter un recours devant les tribunaux de celle-ci lorsque la loi le permet. **[À RÉVISER PAR UN AVOCAT]**

## 19. Langue

Les présentes Conditions sont offertes en français et en anglais. Les deux versions font également foi. Les parties ont expressément exigé que les présentes Conditions et tous les documents qui s’y rattachent soient rédigés en français et en anglais.

## 20. Dispositions générales

Si une disposition des présentes Conditions est jugée inapplicable, les autres demeurent en vigueur. Le fait que nous n’exercions pas un droit ne constitue pas une renonciation à celui-ci. Vous ne pouvez céder les présentes Conditions sans notre consentement; nous pouvons les céder dans le cadre d’une fusion, d’une acquisition ou d’une vente d’actifs. Les présentes Conditions, avec les politiques qui y sont mentionnées, constituent l’entente intégrale entre vous et nous concernant la Plateforme.

## 21. Nous joindre

{{ company_legal_name }}
{{ company_address }}
Courriel : {{ support_email }}
Site Web : {{ website }}
""",
        },
    },
    # ------------------------------------------------------------------
    # 2. Privacy Policy
    # ------------------------------------------------------------------
    {
        'type': 'privacy',
        'audience': 'all',
        'title': {
            'en': 'Privacy Policy',
            'fr': 'Politique de confidentialité',
        },
        'summary': {
            'en': """- We collect what we need to run safe rides: your account details, phone number, trip locations, payments and, for drivers, documents and background checks.
- We track location during active trips only, and keep trip route data for {{ tracking_retention_days }} days unless it is needed for a safety case or dispute.
- Stripe handles your card; we never store your full card number.
- Some of our service providers (Stripe, Twilio, OneSignal, Google) are in the United States, so your data may be processed there.
- We never sell your personal information. Marketing messages are only sent if you opt in, and you can unsubscribe at any time.
- You can access, correct, download or delete your data, or withdraw consent, by contacting our Privacy Officer at {{ support_email }}.
""",
            'fr': """- Nous recueillons ce qui est nécessaire pour offrir des courses sécuritaires : les données de votre compte, votre numéro de téléphone, la localisation des courses, les paiements et, pour les chauffeurs, les documents et la vérification des antécédents.
- Nous suivons votre localisation seulement pendant les courses actives et conservons les données d’itinéraire pendant {{ tracking_retention_days }} jours, sauf si elles sont nécessaires à un dossier de sécurité ou à un différend.
- Stripe traite votre carte; nous ne conservons jamais le numéro complet de votre carte.
- Certains de nos fournisseurs (Stripe, Twilio, OneSignal, Google) sont situés aux États-Unis; vos renseignements peuvent donc y être traités.
- Nous ne vendons jamais vos renseignements personnels. Nous vous envoyons des messages de marketing seulement si vous y consentez, et vous pouvez vous désabonner en tout temps.
- Vous pouvez consulter, corriger, obtenir ou faire supprimer vos renseignements, ou retirer votre consentement, en écrivant à notre responsable de la protection des renseignements personnels à {{ support_email }}.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

{{ company_legal_name }} ("NegoRide", "we", "us") respects your privacy. This Privacy Policy explains how we collect, use, disclose, retain and protect personal information when you use our mobile apps, our website at {{ website }} and related services (the "Platform"). It is designed to comply with the *Personal Information Protection and Electronic Documents Act* (PIPEDA), Québec's *Act respecting the protection of personal information in the private sector* as amended by Law 25, and other applicable provincial privacy laws. **[REVIEW WITH COUNSEL]** — confirm applicability of Alberta and British Columbia PIPA for local operations.

## 1. Accountability and our Privacy Officer

We have designated a Privacy Officer who is responsible for our compliance with this policy and with privacy law. You can reach the Privacy Officer at:

Privacy Officer, {{ company_legal_name }}
{{ company_address }}
Email: {{ support_email }} (subject line: "Privacy Officer")

For Québec purposes, the Privacy Officer is the person in charge of the protection of personal information, and their title and contact information are published on our website. **[REVIEW WITH COUNSEL]** — confirm whether a dedicated privacy email address should be published.

## 2. Information we collect

**Information you give us**

- **Account information:** name, email address, mobile phone number, password (stored only in hashed form), profile photo, preferred language.
- **Driver information:** date of birth, address, driver's licence, vehicle registration, proof of insurance (including rideshare endorsement where required), vehicle photos, a selfie for identity matching, banking or payout details (held by Stripe), and tax information where required.
- **Communications:** in-app messages, negotiation offers, support tickets, safety reports and ratings.
- **Trusted contacts:** names and phone numbers you choose to add for trip sharing. Please add only people who have agreed to receive these messages.

**Information collected when you use the Platform**

- **Location:** precise location of Riders and Drivers during active trips (from request or acceptance to completion), used to match, navigate, show the live route, detect route deviations, calculate fares and handle safety incidents. Drivers' location is also collected while they are online and available. We do not track Riders' location in the background outside a trip.
- **Trip information:** pickup and destination, route breadcrumbs, times, distance, negotiated price, cancellations, waiting time and ratings.
- **Device and usage information:** device model, operating system, app version, IP address, push-notification token, crash logs and in-app activity.
- **Audio recordings:** only if you or the other party turn on optional in-trip audio recording. See our Audio Recording Notice.

**Information from third parties**

- **Phone verification:** Twilio sends us the result of your one-time code verification.
- **Payments:** Stripe tells us whether a payment or authorization succeeded, the card brand and last four digits, and payout status. **We never receive or store your full card number.**
- **Background checks (Drivers only):** with your express consent, Certn provides us with the results of your criminal record check, identity verification and driver's abstract.
- **Other users:** for example, ratings or a safety report about you.

## 3. Why we use your information

We use personal information only for purposes a reasonable person would consider appropriate, namely to:

1. create and manage your account and verify your identity and phone number;
2. connect Riders and Drivers, enable price negotiation and seat booking, and provide navigation;
3. process authorizations, payments, refunds, payouts and receipts;
4. assess Driver eligibility, including documents and background checks;
5. promote safety: SOS response, ride PIN, trip sharing, route-deviation alerts, incident investigation and, where enabled, audio recordings;
6. provide customer support and resolve disputes;
7. enforce our Terms and Community Guidelines, including reliability strikes, suspensions and appeals;
8. detect and prevent fraud, abuse and security incidents;
9. comply with legal obligations, including tax and law-enforcement requests;
10. improve the Platform using aggregated or de-identified information;
11. send you marketing messages — **only with your separate, express consent**.

We do not use automated processing alone to make decisions that have a significant effect on you without offering human review. Where a decision (such as an automatic temporary suspension for reliability strikes) is based exclusively on automated processing, we will inform you and you may ask for a review by a person. **[REVIEW WITH COUNSEL]** — Québec Law 25, s. 12.1 disclosure.

## 4. Consent

We rely on your consent, which may be express or implied depending on the sensitivity of the information. We ask for **express consent** for sensitive processing, such as background checks, precise location, audio recording and marketing. Marketing consent is requested separately from acceptance of the Terms, is never pre-ticked, and complies with Canada's Anti-Spam Legislation (CASL). You may withdraw consent at any time, subject to legal or contractual restrictions; withdrawing some consents (for example, location during a trip) may mean we can no longer provide a service.

## 5. How we share information

We do not sell your personal information. We share it only as follows:

- **Between Riders and Drivers:** first name, profile photo, rating, pickup and drop-off points, and (for Drivers) vehicle make, model, colour and licence plate. We mask phone numbers where possible.
- **Trusted contacts:** a live trip-sharing link you choose to send, which expires after the trip.
- **Service providers** acting on our behalf under contracts that require them to protect your information: Stripe (payments), Twilio (SMS verification), OneSignal (push notifications), Google (maps and routing), Certn (background checks), and our cloud hosting providers.
- **Law enforcement and authorities:** when required by law, in response to a valid legal request, or in an emergency involving a risk to someone's life, health or security. See our Safety Policy.
- **Business transfers:** in connection with a merger, acquisition or sale of assets, subject to confidentiality obligations.

## 6. Transfers outside Canada

Several of our service providers — including Stripe, Twilio, OneSignal and Google — are based in the United States or store information there. Your information may therefore be processed outside Canada and outside Québec and may be accessible to courts, law-enforcement and national-security authorities of those jurisdictions. Before transferring personal information outside Québec, we assess whether it will receive adequate protection, as required by Law 25. **[REVIEW WITH COUNSEL]** — document privacy impact assessments for each cross-border transfer.

## 7. Retention

We keep personal information only as long as necessary for the purposes described, or as required by law:

| Information | Retention |
|---|---|
| Trip route breadcrumbs (detailed GPS points) | {{ tracking_retention_days }} days, unless linked to an incident, report or dispute |
| Audio recordings | {{ recording_retention_days }} days, unless linked to an incident, report or dispute (then until the case closes plus {{ recording_hold_after_case_days }} days) |
| Trip summaries, receipts and payment records | As required by tax and accounting law (generally 6 to 7 years) **[REVIEW WITH COUNSEL]** |
| Driver documents and background check results | While the Driver account is active, then as required by law **[REVIEW WITH COUNSEL]** |
| Account information | While your account is open; then deleted or anonymized, except where retention is required |

When information is no longer needed, we securely destroy it or anonymize it.

## 8. Security

We use administrative, technical and physical safeguards appropriate to the sensitivity of the information, including encryption in transit, encryption of recordings at rest, access controls on a need-to-know basis, audit logging of access to sensitive data, and regular security reviews. No system is perfectly secure, so please protect your password and device.

## 9. Breach notification

If a breach of security safeguards involving your personal information creates a real risk of significant harm (or, in Québec, a risk of serious injury), we will notify you and report it to the Office of the Privacy Commissioner of Canada and, where applicable, the Commission d'accès à l'information du Québec, and keep a record of the incident, as required by law.

## 10. Your rights

Subject to legal exceptions, you have the right to:

- **access** the personal information we hold about you;
- **correct** inaccurate or incomplete information;
- **withdraw consent** to certain processing;
- **request deletion** of your account and personal information (some records must be kept by law);
- **data portability** — receive your information in a structured, commonly used technological format, where Québec law provides this right;
- ask that we stop disseminating your information or de-index links where required by Québec law;
- be informed about automated decisions and ask for human review.

To exercise these rights, use the settings in the app or write to our Privacy Officer at {{ support_email }}. We will respond within 30 days and may need to verify your identity. You cannot request another person's audio recording through the app; see the Audio Recording Notice.

## 11. Children

The Platform is intended for people 18 years of age or older. You must be 18 or older to hold an account. Minors may travel only when accompanied by an adult account holder who is responsible for them. We do not knowingly collect information from children; if we learn that we have, we will delete it.

## 12. Cookies on our website

Our website uses essential cookies to function and, with your consent where required, analytics cookies to understand how it is used. You can control cookies through your browser settings or the cookie banner. The mobile apps do not use advertising cookies.

## 13. Complaints

If you have a concern, please contact our Privacy Officer first. If you are not satisfied, you may complain to:

- the **Office of the Privacy Commissioner of Canada** (priv.gc.ca); or
- for Québec residents, the **Commission d'accès à l'information du Québec** (cai.gouv.qc.ca);
- or the privacy commissioner of your province, where applicable.

## 14. Changes to this policy

We may update this policy. We will notify you of material changes in the app or by email and, where required, seek your consent again. The version number is shown in the app.
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

{{ company_legal_name }} (« NegoRide » ou « nous ») respecte votre vie privée. La présente Politique de confidentialité explique comment nous recueillons, utilisons, communiquons, conservons et protégeons les renseignements personnels lorsque vous utilisez nos applications mobiles, notre site Web {{ website }} et les services connexes (la « Plateforme »). Elle vise à respecter la *Loi sur la protection des renseignements personnels et les documents électroniques* (LPRPDE), la *Loi sur la protection des renseignements personnels dans le secteur privé* du Québec, telle que modifiée par la Loi 25, et les autres lois provinciales applicables en matière de protection de la vie privée. **[À RÉVISER PAR UN AVOCAT]** — confirmer l’application des lois PIPA de l’Alberta et de la Colombie-Britannique pour les activités locales.

## 1. Responsabilité et responsable de la protection des renseignements personnels

Nous avons désigné une personne responsable de la protection des renseignements personnels, chargée de veiller au respect de la présente politique et des lois applicables. Vous pouvez la joindre à l’adresse suivante :

Responsable de la protection des renseignements personnels, {{ company_legal_name }}
{{ company_address }}
Courriel : {{ support_email }} (objet : « Responsable de la protection des renseignements personnels »)

Conformément à la loi québécoise, le titre et les coordonnées de cette personne sont publiés sur notre site Web. **[À RÉVISER PAR UN AVOCAT]** — déterminer s’il convient de publier une adresse courriel dédiée à la protection de la vie privée.

## 2. Renseignements que nous recueillons

**Renseignements que vous nous fournissez**

- **Renseignements de compte :** nom, adresse courriel, numéro de téléphone mobile, mot de passe (conservé uniquement sous forme hachée), photo de profil, langue préférée.
- **Renseignements sur les chauffeurs :** date de naissance, adresse, permis de conduire, certificat d’immatriculation, preuve d’assurance (y compris l’avenant pour le covoiturage commercial lorsqu’il est exigé), photos du véhicule, égoportrait servant à la vérification d’identité, coordonnées bancaires ou de versement (détenues par Stripe) et renseignements fiscaux lorsque requis.
- **Communications :** messages dans l’application, offres de négociation, billets de soutien, signalements de sécurité et évaluations.
- **Contacts de confiance :** noms et numéros de téléphone que vous choisissez d’ajouter pour le partage du trajet. Veuillez n’ajouter que des personnes qui ont accepté de recevoir ces messages.

**Renseignements recueillis lorsque vous utilisez la Plateforme**

- **Localisation :** position précise des passagers et des chauffeurs pendant les courses actives (de la demande ou de l’acceptation jusqu’à la fin de la course), utilisée pour le jumelage, la navigation, l’affichage du trajet en temps réel, la détection des écarts d’itinéraire, le calcul des tarifs et la gestion des incidents de sécurité. La position des chauffeurs est aussi recueillie lorsqu’ils sont en ligne et disponibles. Nous ne suivons pas la position des passagers en arrière-plan en dehors d’une course.
- **Renseignements sur les courses :** point de prise en charge et destination, tracé de l’itinéraire, heures, distance, prix négocié, annulations, temps d’attente et évaluations.
- **Renseignements sur l’appareil et l’utilisation :** modèle de l’appareil, système d’exploitation, version de l’application, adresse IP, jeton de notification, journaux de plantage et activité dans l’application.
- **Enregistrements audio :** seulement si vous ou l’autre partie activez l’enregistrement audio facultatif pendant la course. Consultez notre Avis sur l’enregistrement audio.

**Renseignements provenant de tiers**

- **Vérification du numéro de téléphone :** Twilio nous transmet le résultat de la vérification de votre code à usage unique.
- **Paiements :** Stripe nous indique si un paiement ou une autorisation a réussi, la marque de la carte et ses quatre derniers chiffres, ainsi que l’état des versements. **Nous ne recevons ni ne conservons jamais le numéro complet de votre carte.**
- **Vérification des antécédents (chauffeurs seulement) :** avec votre consentement exprès, Certn nous transmet les résultats de votre vérification du casier judiciaire, de la vérification de votre identité et de votre dossier de conduite.
- **Autres utilisateurs :** par exemple, une évaluation ou un signalement de sécurité vous concernant.

## 3. Pourquoi nous utilisons vos renseignements

Nous utilisons les renseignements personnels uniquement à des fins qu’une personne raisonnable jugerait appropriées, soit pour :

1. créer et gérer votre compte et vérifier votre identité et votre numéro de téléphone;
2. mettre en relation passagers et chauffeurs, permettre la négociation du prix et la réservation de places, et offrir la navigation;
3. traiter les autorisations, paiements, remboursements, versements et reçus;
4. évaluer l’admissibilité des chauffeurs, y compris leurs documents et la vérification de leurs antécédents;
5. favoriser la sécurité : intervention SOS, NIP de course, partage du trajet, alertes d’écart d’itinéraire, enquêtes sur les incidents et, lorsqu’il est activé, enregistrement audio;
6. offrir du soutien à la clientèle et régler les différends;
7. faire respecter nos Conditions d’utilisation et nos Lignes directrices de la communauté, y compris les manquements de fiabilité, les suspensions et les contestations;
8. détecter et prévenir la fraude, les abus et les incidents de sécurité;
9. respecter nos obligations légales, notamment en matière fiscale et à l’égard des demandes des forces de l’ordre;
10. améliorer la Plateforme à l’aide de renseignements agrégés ou dépersonnalisés;
11. vous envoyer des messages de marketing — **uniquement avec votre consentement exprès et distinct**.

Nous ne prenons pas de décisions ayant un effet important sur vous uniquement au moyen d’un traitement automatisé sans offrir une révision par une personne. Lorsqu’une décision (comme une suspension temporaire automatique pour manquements de fiabilité) est fondée exclusivement sur un traitement automatisé, nous vous en informons et vous pouvez demander qu’une personne la révise. **[À RÉVISER PAR UN AVOCAT]** — avis prévu à l’article 12.1 de la loi québécoise.

## 4. Consentement

Nous nous appuyons sur votre consentement, qui peut être exprès ou implicite selon la sensibilité des renseignements. Nous demandons un **consentement exprès** pour les traitements sensibles, comme la vérification des antécédents, la localisation précise, l’enregistrement audio et le marketing. Le consentement au marketing est demandé séparément de l’acceptation des Conditions d’utilisation, n’est jamais coché d’avance et respecte la Loi canadienne anti-pourriel (LCAP). Vous pouvez retirer votre consentement en tout temps, sous réserve de restrictions légales ou contractuelles; le retrait de certains consentements (par exemple, la localisation pendant une course) peut nous empêcher de fournir un service.

## 5. Communication de renseignements

Nous ne vendons pas vos renseignements personnels. Nous les communiquons uniquement dans les cas suivants :

- **Entre passagers et chauffeurs :** prénom, photo de profil, évaluation, points de prise en charge et de dépôt et, pour les chauffeurs, marque, modèle, couleur et plaque d’immatriculation du véhicule. Nous masquons les numéros de téléphone lorsque c’est possible.
- **Contacts de confiance :** le lien de partage du trajet en temps réel que vous choisissez d’envoyer, qui expire après la course.
- **Fournisseurs de services** agissant en notre nom en vertu de contrats les obligeant à protéger vos renseignements : Stripe (paiements), Twilio (vérification par texto), OneSignal (notifications), Google (cartes et itinéraires), Certn (vérification des antécédents) et nos hébergeurs infonuagiques.
- **Forces de l’ordre et autorités :** lorsque la loi l’exige, en réponse à une demande légale valide ou en cas d’urgence mettant en danger la vie, la santé ou la sécurité d’une personne. Consultez notre Politique de sécurité.
- **Transactions commerciales :** dans le cadre d’une fusion, d’une acquisition ou d’une vente d’actifs, sous réserve d’obligations de confidentialité.

## 6. Communication à l’extérieur du Canada

Plusieurs de nos fournisseurs de services — notamment Stripe, Twilio, OneSignal et Google — sont établis aux États-Unis ou y conservent des renseignements. Vos renseignements peuvent donc être traités à l’extérieur du Canada et du Québec et être accessibles aux tribunaux, aux forces de l’ordre et aux autorités chargées de la sécurité nationale de ces territoires. Avant de communiquer des renseignements personnels à l’extérieur du Québec, nous évaluons s’ils bénéficieront d’une protection adéquate, comme l’exige la Loi 25. **[À RÉVISER PAR UN AVOCAT]** — documenter les évaluations des facteurs relatifs à la vie privée pour chaque communication transfrontalière.

## 7. Conservation

Nous conservons les renseignements personnels seulement le temps nécessaire aux fins décrites ou exigé par la loi :

| Renseignements | Durée de conservation |
|---|---|
| Tracé détaillé des courses (points GPS) | {{ tracking_retention_days }} jours, sauf s’il est lié à un incident, à un signalement ou à un différend |
| Enregistrements audio | {{ recording_retention_days }} jours, sauf s’ils sont liés à un incident, à un signalement ou à un différend (ils sont alors conservés jusqu’à la clôture du dossier, plus {{ recording_hold_after_case_days }} jours) |
| Sommaires de course, reçus et dossiers de paiement | Selon les exigences des lois fiscales et comptables (généralement de 6 à 7 ans) **[À RÉVISER PAR UN AVOCAT]** |
| Documents des chauffeurs et résultats de la vérification des antécédents | Tant que le compte chauffeur est actif, puis selon les exigences légales **[À RÉVISER PAR UN AVOCAT]** |
| Renseignements de compte | Tant que votre compte est ouvert; ils sont ensuite supprimés ou anonymisés, sauf obligation de conservation |

Lorsque des renseignements ne sont plus nécessaires, nous les détruisons de façon sécuritaire ou les anonymisons.

## 8. Sécurité

Nous appliquons des mesures de sécurité administratives, techniques et physiques adaptées à la sensibilité des renseignements, notamment le chiffrement des données en transit, le chiffrement des enregistrements stockés, un accès limité selon le principe du besoin de savoir, la journalisation des accès aux données sensibles et des examens de sécurité réguliers. Aucun système n’est parfaitement sûr; protégez donc votre mot de passe et votre appareil.

## 9. Avis en cas d’incident de confidentialité

Si une atteinte aux mesures de sécurité visant vos renseignements personnels présente un risque réel de préjudice grave (ou, au Québec, un risque qu’un préjudice sérieux soit causé), nous vous en aviserons, nous le déclarerons au Commissariat à la protection de la vie privée du Canada et, s’il y a lieu, à la Commission d’accès à l’information du Québec, et nous tiendrons un registre de l’incident, comme l’exige la loi.

## 10. Vos droits

Sous réserve des exceptions prévues par la loi, vous avez le droit :

- d’**accéder** aux renseignements personnels que nous détenons à votre sujet;
- de **faire rectifier** des renseignements inexacts ou incomplets;
- de **retirer votre consentement** à certains traitements;
- de **demander la suppression** de votre compte et de vos renseignements personnels (certains dossiers doivent être conservés en vertu de la loi);
- à la **portabilité des données** — recevoir vos renseignements dans un format technologique structuré et couramment utilisé, lorsque la loi québécoise prévoit ce droit;
- de demander que nous cessions de diffuser vos renseignements ou que nous désindexions certains hyperliens, lorsque la loi québécoise l’exige;
- d’être informé des décisions automatisées et d’en demander la révision par une personne.

Pour exercer ces droits, utilisez les paramètres de l’application ou écrivez à notre responsable de la protection des renseignements personnels à {{ support_email }}. Nous répondrons dans un délai de 30 jours et pourrions devoir vérifier votre identité. Vous ne pouvez pas obtenir l’enregistrement audio d’une autre personne au moyen de l’application; consultez l’Avis sur l’enregistrement audio.

## 11. Enfants

La Plateforme s’adresse aux personnes âgées de 18 ans ou plus. Vous devez avoir 18 ans ou plus pour détenir un compte. Les mineurs ne peuvent voyager qu’accompagnés d’un adulte titulaire d’un compte qui en est responsable. Nous ne recueillons pas sciemment de renseignements sur des enfants; si nous apprenons que cela s’est produit, nous les supprimerons.

## 12. Témoins (cookies) sur notre site Web

Notre site Web utilise des témoins essentiels à son fonctionnement et, avec votre consentement lorsque la loi l’exige, des témoins analytiques pour comprendre son utilisation. Vous pouvez gérer les témoins dans les paramètres de votre navigateur ou au moyen du bandeau de consentement. Les applications mobiles n’utilisent pas de témoins publicitaires.

## 13. Plaintes

Si vous avez une préoccupation, veuillez d’abord communiquer avec notre responsable de la protection des renseignements personnels. Si vous n’êtes pas satisfait, vous pouvez porter plainte auprès :

- du **Commissariat à la protection de la vie privée du Canada** (priv.gc.ca);
- pour les résidents du Québec, de la **Commission d’accès à l’information du Québec** (cai.gouv.qc.ca);
- ou du commissaire à la protection de la vie privée de votre province, s’il y a lieu.

## 14. Modification de la présente politique

Nous pouvons mettre à jour la présente politique. Nous vous aviserons de toute modification importante dans l’application ou par courriel et, lorsque la loi l’exige, nous vous demanderons à nouveau votre consentement. Le numéro de version est affiché dans l’application.
""",
        },
    },
    # ------------------------------------------------------------------
    # 3. Community Guidelines
    # ------------------------------------------------------------------
    {
        'type': 'community_guidelines',
        'audience': 'all',
        'title': {
            'en': 'Community Guidelines',
            'fr': 'Lignes directrices de la communauté',
        },
        'summary': {
            'en': """- Treat everyone with respect. We have zero tolerance for discrimination, harassment and violence.
- Negotiate fairly: make honest offers, and once a price is agreed in the app, it's final. No off-app cash deals.
- Everyone buckles up. Riders bring the child car seats their children need.
- Service animals must always be accepted. That is the law.
- Drivers must never be impaired. Zero tolerance for alcohol, cannabis and drugs.
- Use the ride PIN, share your trip, and call 911 in an emergency.
- Breaking these rules can lead to a warning, suspension or permanent ban. You can appeal any decision.
""",
            'fr': """- Traitez tout le monde avec respect. Nous appliquons une tolérance zéro envers la discrimination, le harcèlement et la violence.
- Négociez de bonne foi : faites des offres honnêtes et, une fois le prix convenu dans l’application, il est définitif. Aucune entente en argent comptant hors application.
- Tout le monde boucle sa ceinture. Les passagers fournissent les sièges d’auto dont leurs enfants ont besoin.
- Les animaux d’assistance doivent toujours être acceptés. C’est la loi.
- Les chauffeurs ne doivent jamais avoir les facultés affaiblies. Tolérance zéro pour l’alcool, le cannabis et les drogues.
- Utilisez le NIP de course, partagez votre trajet et composez le 911 en cas d’urgence.
- Le non-respect de ces règles peut entraîner un avertissement, une suspension ou un bannissement définitif. Vous pouvez contester toute décision.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

NegoRide is built on a simple idea: two people agree on a fair price and share a safe, respectful trip. These Community Guidelines apply to everyone who uses the Platform — Riders, Drivers, couriers, movers and anyone travelling with them — before, during and after a trip, including in in-app messages and negotiations. They form part of our Terms & Conditions. If you have questions, contact us at {{ support_email }}.

## 1. Respect for everyone

Treat every person as you would like to be treated. Be courteous, keep conversations appropriate, and respect personal space. Drivers and Riders come from every background and community across Canada; everyone deserves dignity. Physical contact with anyone you don't know is not acceptable, and raising your voice, threatening, or using abusive or obscene language is never allowed.

Respect each other's preferences where reasonable: some people like to chat and some prefer quiet; some want music and others don't. Drivers should ask before adjusting temperature or audio to extremes, and Riders should respect that the vehicle belongs to the Driver.

## 2. Zero tolerance for discrimination

We do not tolerate discrimination of any kind. It is prohibited to refuse, cancel, rate lower, charge a different price, or otherwise treat anyone differently because of race, ancestry, place of origin, colour, ethnic origin, citizenship, creed or religion, sex, pregnancy, sexual orientation, gender identity, gender expression, age, marital or family status, disability, language, social condition, or any other ground protected by federal, provincial or territorial human-rights law.

This includes the negotiation stage: making different offers, or refusing to negotiate, based on a person's name, photo, pickup neighbourhood or any protected characteristic is discrimination.

Riders with disabilities must be offered the same service as everyone else. Drivers must provide reasonable assistance (for example, storing a folding wheelchair or walker in the trunk) where it is safe to do so. **[REVIEW WITH COUNSEL]** — confirm duty-to-accommodate obligations under provincial accessibility statutes (e.g., AODA).

A violation of this section may lead to immediate and permanent deactivation.

## 3. Zero tolerance for harassment

Harassment of any kind is prohibited, including:

- **sexual harassment** — sexual comments or jokes, questions about someone's relationships or appearance, flirting, touching, or any sexual conduct. Drivers and Riders must never engage in sexual activity with each other during a trip, regardless of consent;
- **unwanted contact after the trip** — using someone's name, phone number, address or other details obtained through NegoRide to contact, follow, visit or connect with them on social media without their clear request;
- threats, intimidation, stalking, bullying, or discussing someone's personal life in a way that makes them uncomfortable;
- recording, photographing or live-streaming someone without their knowledge, other than through NegoRide's in-app audio recording feature, which notifies the other party.

## 4. No weapons

Weapons, including firearms, ammunition, knives intended as weapons, bear spray, pepper spray and replica weapons, are not permitted in vehicles during trips, even where otherwise lawful, except where a person is a law-enforcement officer required by law to carry one. **[REVIEW WITH COUNSEL]** — confirm exceptions (e.g., ceremonial kirpan, which should be accommodated as a religious article).

## 5. Drugs and alcohol

- **Drivers: zero tolerance.** Drivers must never drive while impaired by alcohol, cannabis, illegal drugs or medications that affect their ability to drive, and must not consume or possess open alcohol or cannabis in the vehicle. If a Rider reports that a Driver may be impaired, we will immediately take the Driver offline while we investigate.
- **Riders** must not bring open containers of alcohol into the vehicle, and must not smoke, vape or use cannabis or drugs during a trip. Drivers may end or refuse a trip if a Rider is visibly intoxicated to the point of being unsafe, abusive or likely to be sick in the vehicle.
- Transporting illegal substances is prohibited for everyone.

## 6. Seat belts and child car seats

- **Everyone buckles up.** Provincial highway traffic laws require every occupant to wear a seat belt. Drivers must not start the trip until everyone is buckled, and Riders must not exceed the number of available seat belts.
- **Child car seats.** Children must be secured in a car seat or booster seat appropriate for their age, weight and height as required by provincial law. **Riders are responsible for bringing and installing their own car seat.** Drivers may decline a trip, without penalty, if an appropriate car seat is not available; the Rider should cancel and will not be charged a cancellation fee in that case. **[REVIEW WITH COUNSEL]** — some provinces exempt taxis from car-seat rules; confirm rules for rideshare vehicles in each province.
- Minors under 18 may not travel alone and must be accompanied by the adult account holder.

## 7. Service animals and pets

- **Service animals must be accepted.** Drivers are legally required to transport Riders with service animals, including guide dogs. Refusing a Rider because of a service animal is discrimination and may result in permanent deactivation. **Allergies, fear of animals or religious objections are not valid reasons to refuse on the spot.** If a Driver has a serious medical condition that conflicts with this obligation, they must contact support at {{ support_email }} in advance so we can discuss accommodation. Drivers may not ask for proof of certification beyond what the law allows. **[REVIEW WITH COUNSEL]**
- Riders should mention a service animal when requesting a trip if possible, but are not required to.
- **Pets** (animals that are not service animals) are at the Driver's discretion. Riders should ask first, use a carrier where possible, and are responsible for any mess.

## 8. Cleanliness and respect for property

Drivers must keep their vehicle clean, odour-free, in good working order, and matching the vehicle registered on the Platform. Riders must treat the vehicle with care. If a Rider causes damage or a mess that requires professional cleaning (for example, spilled food, vomit or bodily fluids), a cleaning or damage fee may be charged after review of photos and evidence provided by the Driver. Riders can dispute such fees through support within 72 hours. Smoking and vaping are not permitted in the vehicle by anyone.

## 9. Fair negotiation etiquette

Negotiation is what makes NegoRide different. To keep it fair for everyone:

- **Make honest offers.** Offer or ask a price you are genuinely willing to pay or accept for the trip described.
- **No lowballing to harass.** Repeatedly sending unrealistic offers to pressure, mock or waste the time of the other person is not allowed.
- **The agreed price is final.** Once both parties accept a price in the app, neither party may change it — unless both agree to a new price through the app (for example, because of an added stop or a new destination).
- **No bait-and-switch.** Drivers must not agree to a price and then demand more at pickup, take a longer route to justify a higher price, or claim extra fees not shown in the app. Riders must not agree to a trip and then change the destination without renegotiating in the app.
- **No off-app cash deals.** Do not ask for or accept cash, e-transfers or other payments outside the app, or arrange future trips off the Platform. Off-app trips have no safety features, no support and no protection.
- **Respond promptly.** Reply to offers quickly or decline them so the other person can move on. Don't accept an offer you don't intend to honour.
- Tips are always optional and must never be demanded.

## 10. Using safety features

- **Check before you get in.** Riders should confirm the Driver's name, photo, vehicle and licence plate and give the Driver the 4-digit ride PIN only once they have confirmed the vehicle is correct. Drivers must not start a trip without the correct PIN.
- **Share your trip** with trusted contacts through the app.
- **Use SOS** to reach NegoRide's 24/7 safety team if you feel unsafe.
- **Call 911 in any emergency.** NegoRide is not an emergency service.
- Never misuse the SOS button or file false safety reports.

## 11. Privacy of contact details

Contact each other only through the app and only about the trip. Do not save, share or reuse another user's phone number, address or photos. Don't post anything about another user online. If you leave something behind, use the Lost Items option in the app rather than contacting the Driver directly.

## 12. Honest ratings

Ratings help keep the community safe. Rate based on the trip — safety, courtesy, cleanliness, punctuality and whether the agreed price was honoured. Do not use ratings to retaliate, pressure someone (e.g., "rate me five stars or I'll rate you one"), or discriminate. We may remove ratings that break these rules. Riders or Drivers with consistently low ratings may lose access to the Platform after warnings.

## 13. Consequences and appeals

Depending on the seriousness and frequency of a violation, we may:

1. send a **warning** and educational reminder;
2. apply a **temporary suspension**;
3. **deactivate** the account;
4. **permanently ban** the person from the Platform.

Serious safety matters — such as violence, sexual misconduct, impaired driving, weapons or discrimination — may result in immediate suspension while we investigate, and permanent removal. We may also report matters to the police where required or appropriate. For Drivers, reliability strikes and suspensions are described in the Driver Agreement and Cancellation & Refund Policy.

You can appeal any decision by opening a support ticket in the app or by emailing {{ support_email }} with any information you want us to consider. A team member who was not involved in the original decision will review the appeal and give you a response.
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

NegoRide repose sur une idée simple : deux personnes s’entendent sur un prix juste et partagent une course sécuritaire et respectueuse. Les présentes Lignes directrices de la communauté s’appliquent à toute personne qui utilise la Plateforme — passagers, chauffeurs, livreurs, déménageurs et toute personne qui les accompagne — avant, pendant et après une course, y compris dans les messages et les négociations dans l’application. Elles font partie de nos Conditions d’utilisation. Pour toute question, écrivez-nous à {{ support_email }}.

## 1. Respect envers tous

Traitez chaque personne comme vous aimeriez être traité. Soyez courtois, gardez des conversations convenables et respectez l’espace personnel de chacun. Les chauffeurs et les passagers proviennent de tous les milieux et de toutes les communautés du Canada; chacun mérite d’être traité avec dignité. Tout contact physique avec une personne que vous ne connaissez pas est inacceptable. Il est toujours interdit d’élever la voix, de proférer des menaces ou d’employer un langage injurieux ou obscène.

Respectez les préférences de chacun dans la mesure du raisonnable : certaines personnes aiment discuter, d’autres préfèrent le silence; certaines veulent de la musique, d’autres non. Les chauffeurs devraient demander avant de régler la température ou le volume de façon extrême, et les passagers devraient se rappeler que le véhicule appartient au chauffeur.

## 2. Tolérance zéro envers la discrimination

Nous ne tolérons aucune forme de discrimination. Il est interdit de refuser une personne, d’annuler sa course, de lui attribuer une note plus basse, de lui demander un prix différent ou de la traiter autrement en raison de sa race, de son ascendance, de son lieu d’origine, de sa couleur, de son origine ethnique, de sa citoyenneté, de sa croyance ou de sa religion, de son sexe, d’une grossesse, de son orientation sexuelle, de son identité ou de son expression de genre, de son âge, de son état civil ou familial, d’un handicap, de sa langue, de sa condition sociale ou de tout autre motif protégé par les lois fédérales, provinciales ou territoriales sur les droits de la personne.

Cela comprend l’étape de la négociation : faire des offres différentes, ou refuser de négocier, en fonction du nom, de la photo, du quartier de prise en charge ou de toute caractéristique protégée d’une personne constitue de la discrimination.

Les passagers ayant un handicap doivent recevoir le même service que tout le monde. Les chauffeurs doivent offrir une aide raisonnable (par exemple, ranger un fauteuil roulant pliant ou une marchette dans le coffre) lorsqu’il est sécuritaire de le faire. **[À RÉVISER PAR UN AVOCAT]** — confirmer les obligations d’accommodement prévues par les lois provinciales sur l’accessibilité (p. ex. la LAPHO en Ontario).

Une violation du présent article peut entraîner une désactivation immédiate et définitive.

## 3. Tolérance zéro envers le harcèlement

Toute forme de harcèlement est interdite, notamment :

- **le harcèlement sexuel** — commentaires ou blagues à caractère sexuel, questions sur la vie amoureuse ou l’apparence d’une personne, avances, attouchements ou tout comportement sexuel. Les chauffeurs et les passagers ne doivent jamais avoir d’activité sexuelle entre eux pendant une course, même avec consentement;
- **les contacts non désirés après la course** — utiliser le nom, le numéro de téléphone, l’adresse ou d’autres renseignements obtenus par NegoRide pour communiquer avec une personne, la suivre, lui rendre visite ou l’ajouter sur les réseaux sociaux sans qu’elle l’ait clairement demandé;
- les menaces, l’intimidation, la traque, l’intimidation répétée ou le fait de parler de la vie personnelle d’une personne d’une manière qui la met mal à l’aise;
- enregistrer, photographier ou diffuser en direct une personne à son insu, sauf au moyen de la fonction d’enregistrement audio de NegoRide, qui avise l’autre partie.

## 4. Aucune arme

Les armes, y compris les armes à feu, les munitions, les couteaux destinés à servir d’arme, le vaporisateur chasse-ours, le vaporisateur de poivre et les répliques d’armes, sont interdites dans les véhicules pendant les courses, même lorsque leur possession est par ailleurs légale, sauf dans le cas d’un agent de la paix tenu par la loi d’en porter une. **[À RÉVISER PAR UN AVOCAT]** — confirmer les exceptions (p. ex. le kirpan cérémoniel, qui devrait être accommodé à titre d’objet religieux).

## 5. Drogues et alcool

- **Chauffeurs : tolérance zéro.** Les chauffeurs ne doivent jamais conduire avec les facultés affaiblies par l’alcool, le cannabis, des drogues illégales ou des médicaments qui nuisent à leur capacité de conduire, et ne doivent pas consommer ni avoir en leur possession de l’alcool ou du cannabis ouvert dans le véhicule. Si un passager signale qu’un chauffeur pourrait avoir les facultés affaiblies, nous le mettrons immédiatement hors ligne pendant notre enquête.
- **Les passagers** ne doivent pas apporter de contenants d’alcool ouverts dans le véhicule, ni fumer, vapoter ou consommer du cannabis ou des drogues pendant une course. Le chauffeur peut refuser ou interrompre une course si un passager est manifestement intoxiqué au point d’être dangereux, injurieux ou susceptible d’être malade dans le véhicule.
- Le transport de substances illégales est interdit à tous.

## 6. Ceinture de sécurité et sièges d’auto pour enfants

- **Tout le monde boucle sa ceinture.** Les codes de la sécurité routière provinciaux exigent que chaque occupant porte la ceinture de sécurité. Le chauffeur ne doit pas commencer la course avant que tout le monde soit attaché, et le nombre de passagers ne doit pas dépasser le nombre de ceintures disponibles.
- **Sièges d’auto pour enfants.** Les enfants doivent être installés dans un siège d’auto ou un siège d’appoint adapté à leur âge, à leur poids et à leur taille, conformément à la loi provinciale. **Il revient aux passagers d’apporter et d’installer leur propre siège d’auto.** Le chauffeur peut refuser une course, sans pénalité, si aucun siège adéquat n’est disponible; le passager devrait alors annuler la course et aucuns frais d’annulation ne lui seront facturés. **[À RÉVISER PAR UN AVOCAT]** — certaines provinces exemptent les taxis des règles sur les sièges d’auto; confirmer les règles applicables aux véhicules de covoiturage commercial dans chaque province.
- Les mineurs de moins de 18 ans ne peuvent pas voyager seuls et doivent être accompagnés de l’adulte titulaire du compte.

## 7. Animaux d’assistance et animaux de compagnie

- **Les animaux d’assistance doivent être acceptés.** Les chauffeurs sont légalement tenus de transporter les passagers accompagnés d’un animal d’assistance, y compris un chien-guide. Refuser un passager en raison de son animal d’assistance constitue de la discrimination et peut entraîner une désactivation définitive. **Les allergies, la peur des animaux ou des objections religieuses ne constituent pas des motifs valables de refus sur place.** Le chauffeur qui a un problème de santé grave incompatible avec cette obligation doit communiquer à l’avance avec le soutien à {{ support_email }} afin que nous puissions discuter d’un accommodement. Les chauffeurs ne peuvent exiger aucune preuve de certification au-delà de ce que permet la loi. **[À RÉVISER PAR UN AVOCAT]**
- Les passagers devraient, si possible, mentionner la présence d’un animal d’assistance lorsqu’ils demandent une course, mais ils n’y sont pas obligés.
- **Les animaux de compagnie** (qui ne sont pas des animaux d’assistance) sont acceptés à la discrétion du chauffeur. Les passagers doivent le demander au préalable, utiliser une cage de transport si possible et sont responsables de tout dégât.

## 8. Propreté et respect des biens

Les chauffeurs doivent garder leur véhicule propre, sans odeur, en bon état de fonctionnement et conforme au véhicule inscrit sur la Plateforme. Les passagers doivent traiter le véhicule avec soin. Si un passager cause des dommages ou un dégât nécessitant un nettoyage professionnel (par exemple, nourriture renversée, vomissures ou liquides biologiques), des frais de nettoyage ou de réparation peuvent lui être facturés après examen des photos et des preuves fournies par le chauffeur. Le passager peut contester ces frais auprès du soutien dans les 72 heures. Personne ne peut fumer ni vapoter dans le véhicule.

## 9. Règles de négociation équitable

La négociation est ce qui distingue NegoRide. Pour qu’elle reste équitable pour tous :

- **Faites des offres honnêtes.** Proposez ou demandez un prix que vous êtes réellement prêt à payer ou à accepter pour la course décrite.
- **Pas d’offres dérisoires pour harceler.** Il est interdit d’envoyer à répétition des offres irréalistes pour faire pression sur l’autre personne, la ridiculiser ou lui faire perdre son temps.
- **Le prix convenu est définitif.** Dès que les deux parties acceptent un prix dans l’application, aucune d’elles ne peut le modifier — à moins que les deux ne conviennent d’un nouveau prix dans l’application (par exemple, en raison d’un arrêt supplémentaire ou d’une nouvelle destination).
- **Pas d’appât et substitution.** Le chauffeur ne doit pas accepter un prix puis exiger davantage lors de la prise en charge, emprunter un trajet plus long pour justifier un prix plus élevé ni réclamer des frais qui ne figurent pas dans l’application. Le passager ne doit pas accepter une course puis changer de destination sans renégocier dans l’application.
- **Aucune entente en argent comptant hors application.** Ne demandez ni n’acceptez d’argent comptant, de virement Interac ou d’autre paiement en dehors de l’application, et n’organisez pas de courses futures hors de la Plateforme. Les courses hors application n’offrent ni fonctions de sécurité, ni soutien, ni protection.
- **Répondez rapidement.** Répondez aux offres sans tarder ou refusez-les pour que l’autre personne puisse passer à autre chose. N’acceptez pas une offre que vous n’avez pas l’intention d’honorer.
- Les pourboires sont toujours facultatifs et ne doivent jamais être exigés.

## 10. Utilisation des fonctions de sécurité

- **Vérifiez avant de monter.** Le passager devrait confirmer le nom, la photo, le véhicule et la plaque d’immatriculation du chauffeur, et ne lui donner le NIP de course à 4 chiffres qu’une fois le véhicule confirmé. Le chauffeur ne doit pas commencer une course sans le bon NIP.
- **Partagez votre trajet** avec des contacts de confiance au moyen de l’application.
- **Utilisez le bouton SOS** pour joindre l’équipe de sécurité de NegoRide, disponible 24 heures sur 24, 7 jours sur 7, si vous vous sentez en danger.
- **Composez le 911 en cas d’urgence.** NegoRide n’est pas un service d’urgence.
- N’utilisez jamais le bouton SOS de façon abusive et ne faites pas de faux signalements.

## 11. Confidentialité des coordonnées

Communiquez entre vous uniquement au moyen de l’application et uniquement au sujet de la course. Ne conservez pas, ne partagez pas et ne réutilisez pas le numéro de téléphone, l’adresse ou les photos d’un autre utilisateur. Ne publiez rien en ligne au sujet d’un autre utilisateur. Si vous oubliez un objet, utilisez l’option Objets perdus de l’application plutôt que de communiquer directement avec le chauffeur.

## 12. Évaluations honnêtes

Les évaluations contribuent à la sécurité de la communauté. Évaluez la course elle-même — sécurité, courtoisie, propreté, ponctualité et respect du prix convenu. N’utilisez pas les évaluations pour exercer des représailles, faire pression (p. ex. « donnez-moi cinq étoiles, sinon je vous en donne une ») ou discriminer. Nous pouvons retirer les évaluations qui enfreignent ces règles. Les passagers ou chauffeurs qui obtiennent régulièrement de faibles évaluations peuvent perdre l’accès à la Plateforme après des avertissements.

## 13. Conséquences et contestation

Selon la gravité et la fréquence d’une violation, nous pouvons :

1. envoyer un **avertissement** accompagné d’un rappel des règles;
2. imposer une **suspension temporaire**;
3. **désactiver** le compte;
4. **bannir définitivement** la personne de la Plateforme.

Les manquements graves en matière de sécurité — comme la violence, l’inconduite sexuelle, la conduite avec facultés affaiblies, les armes ou la discrimination — peuvent entraîner une suspension immédiate pendant l’enquête et un retrait définitif. Nous pouvons aussi signaler la situation à la police lorsque la loi l’exige ou que c’est approprié. Pour les chauffeurs, les manquements de fiabilité et les suspensions sont décrits dans le Contrat du chauffeur et la Politique d’annulation et de remboursement.

Vous pouvez contester toute décision en ouvrant un billet de soutien dans l’application ou en écrivant à {{ support_email }}, en joignant tout renseignement que vous souhaitez nous soumettre. Un membre de l’équipe qui n’a pas participé à la décision initiale examinera votre contestation et vous répondra.
""",
        },
    },
    # ------------------------------------------------------------------
    # 4. Driver Agreement
    # ------------------------------------------------------------------
    {
        'type': 'driver_agreement',
        'audience': 'driver',
        'title': {
            'en': 'Driver Agreement',
            'fr': 'Contrat du chauffeur',
        },
        'summary': {
            'en': """- You are an independent contractor, not an employee. You choose when, where and whether to drive.
- You must be at least {{ min_driver_age }}, hold a valid full licence, drive a {{ min_vehicle_year }} or newer vehicle, and carry the insurance your province requires.
- Keep your documents valid. You can't go online with expired documents, and background checks are repeated every {{ recheck_months }} months.
- NegoRide keeps a {{ commission_pct }}% commission on each fare. Payouts go to you through Stripe Connect.
- You are responsible for your own taxes, including GST/HST registration where required.
- Repeated cancellations or no-shows lead to reliability strikes, warnings and temporary suspensions.
- You can appeal any deactivation through a support ticket.
""",
            'fr': """- Vous êtes un entrepreneur indépendant, et non un employé. Vous choisissez quand, où et si vous conduisez.
- Vous devez avoir au moins {{ min_driver_age }} ans, être titulaire d’un permis de conduire complet valide, conduire un véhicule de l’année {{ min_vehicle_year }} ou plus récent et détenir l’assurance exigée dans votre province.
- Gardez vos documents à jour. Vous ne pouvez pas vous mettre en ligne avec des documents expirés, et la vérification des antécédents est refaite tous les {{ recheck_months }} mois.
- NegoRide retient une commission de {{ commission_pct }} % sur chaque tarif. Vos versements vous sont faits par Stripe Connect.
- Vous êtes responsable de vos propres impôts et taxes, y compris l’inscription aux fins de la TPS/TVH lorsqu’elle est requise.
- Les annulations ou non-présentations répétées entraînent des manquements de fiabilité, des avertissements et des suspensions temporaires.
- Vous pouvez contester toute désactivation au moyen d’un billet de soutien.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

This Driver Agreement (the "Agreement") is between you, the individual applying to offer services through the NegoRide Platform ("you" or the "Driver"), and {{ company_legal_name }}, {{ company_address }} ("NegoRide", "we" or "us"). It supplements our Terms & Conditions, Privacy Policy, Community Guidelines, Cancellation & Refund Policy, Safety Policy and Audio Recording Notice, which also apply to you. If there is a conflict, this Agreement governs your relationship with us as a Driver.

## 1. Independent contractor relationship

You are an independent contractor. You are not an employee, agent, partner or franchisee of NegoRide. **[REVIEW WITH COUNSEL]** — review against provincial employment standards (e.g., Ontario's *Digital Platform Workers' Rights Act, 2022*) and adapt disclosures accordingly.

- You decide whether, when, where and for how long to log in, and which trip requests, negotiations or seat bookings to accept.
- You are free to use other platforms or run your own business at the same time.
- You supply and maintain your own vehicle, phone, data plan, fuel and other equipment at your own cost.
- NegoRide does not control how you perform a trip, other than requiring compliance with the law, safety rules and our policies.
- You are not entitled to employee benefits, and NegoRide will not withhold income tax, CPP/QPP or EI contributions from your earnings, except where required by law.

## 2. Eligibility

To drive on NegoRide, you must at all times:

- be at least **{{ min_driver_age }}** years old;
- hold a valid, full (non-probationary, non-graduated) driver's licence for the province in which you drive, with the class required for the service offered;
- have the legal right to work in Canada;
- drive a vehicle with a model year of **{{ min_vehicle_year }}** or newer that is safe, clean, registered, has four doors (for passenger services) and passes any inspection required by your province or municipality;
- carry valid automobile insurance for the vehicle, **including a rideshare / transportation network endorsement where required by your province or insurer**, and any municipal vehicle-for-hire licence required where you operate. **[REVIEW WITH COUNSEL]** — confirm province-by-province insurance and licensing requirements and whether NegoRide will hold a fleet policy covering trip periods;
- pass our onboarding: phone verification, document review, a background check through Certn, admin review and our safety orientation.

## 3. Documents and keeping them valid

You must upload your licence, vehicle registration, proof of insurance, vehicle photos and a selfie for identity verification, and keep all of them current and accurate. We will send reminders before documents expire. **You cannot go online with expired or missing documents**; your account will be paused automatically until updated documents are approved. You must notify us within 48 hours of any change to your licence status (including suspensions, new convictions or demerit points that affect eligibility), insurance or vehicle.

## 4. Background checks

With your separate express consent (see the Background Check Consent), NegoRide will obtain a background check through Certn, including a Canadian criminal record check, identity verification and a driver's abstract. You pay the background check fee. Checks are repeated **every {{ recheck_months }} months**, and we may request a new check at any time if we receive information suggesting your eligibility may have changed, where permitted by law. Adjudication decisions will be made fairly and consistently with applicable human-rights law, considering the relevance of any record to the work. **[REVIEW WITH COUNSEL]**

## 5. Fares, negotiation and commission

- **Car Hire:** you and the Rider negotiate a price in the app. Once both accept, the agreed price is final. You must not demand extra money, take a longer route, or add charges not shown in the app. Price changes require both parties' agreement in the app.
- **Rideshare:** you set a price per seat for published journeys, within any limits we set.
- **Commission:** NegoRide retains a service commission of **{{ commission_pct }}%** of each fare (excluding tips, which you keep in full). The commission rate may change on at least 30 days' notice in the app; the rate in force when a trip is confirmed applies to that trip.
- Waiting-time charges, cancellation fees and no-show fees collected under the Cancellation & Refund Policy are paid to you less the commission, unless the policy provides otherwise.
- You must never accept cash or off-app payments for trips arranged through NegoRide.

## 6. Payouts

Payouts are made through **Stripe Connect**. You must complete Stripe's identity verification and provide a Canadian bank account. Earnings are paid out on the schedule shown in the app, after the trip is completed and payment is captured. We may hold a payout while investigating a dispute, chargeback, fraud or safety incident, and may deduct from your earnings amounts owed to Riders (for example, refunds for overcharges) or to NegoRide. You will receive earnings statements in the app.

## 7. Taxes

**You are responsible for your own taxes**, including income tax on your earnings and any obligation to register for, collect and remit GST/HST (and QST in Québec). Under current federal rules, drivers providing taxi and commercial ride-sharing services are generally required to register for GST/HST from their first trip, even if their revenues are below the $30,000 small-supplier threshold that applies to most other businesses. **[REVIEW WITH COUNSEL]** — confirm treatment for Car Hire, Rideshare, courier and moving services and whether NegoRide collects and remits on drivers' behalf. We will provide annual earnings summaries and may be required to report your earnings to the Canada Revenue Agency or Revenu Québec under digital-platform reporting rules.

## 8. Cancellations, no-shows and reliability strikes

Riders depend on you once you confirm a trip. You receive a **reliability strike** when you cancel after confirmation (other than for a valid safety reason or a Rider's breach of the Community Guidelines), or when you fail to arrive by the ETA plus the grace period described in the Cancellation & Refund Policy (a Driver no-show).

- More than **{{ strikes_warn_after }}** strikes within **{{ strikes_window_days }}** days results in a **warning**.
- More than **{{ strikes_suspend_after }}** strikes within **{{ strikes_window_days }}** days results in a **temporary suspension of {{ strikes_suspend_days }} days**.
- Repeated suspensions may lead to deactivation.

You can dispute a strike through a support ticket if you believe it was applied in error (for example, the Rider asked you to cancel, or you cancelled for safety reasons).

## 9. Ratings

Riders rate you after each trip, and you rate Riders. Your rating is an average of your recent rated trips. If your rating falls below the minimum shown in the app, we will warn you and offer resources to improve. If it stays below the minimum, we may suspend or deactivate your account. Ratings we determine to be discriminatory or retaliatory will be excluded.

## 10. Safety obligations

You agree to:

- obey all traffic laws and never drive while impaired, fatigued or distracted (no handheld phone use while driving);
- verify the ride PIN before starting a trip and ensure all passengers wear seat belts;
- keep your vehicle safe and maintained, including appropriate winter tires where required by law;
- take reasonable rest breaks and not drive more hours than is safe (see the Safety Policy);
- report any accident, injury or safety incident through the app immediately and cooperate with our safety team;
- complete our safety orientation and any refresher training we require.

You may flag a Rider, end a trip or refuse a trip if you feel unsafe; use SOS or call 911 in an emergency.

## 11. Non-discrimination and service animals

You must not discriminate against any Rider on any ground protected by human-rights law, including in negotiation, acceptance, cancellation or rating. **You must accept Riders with service animals** — this is a legal requirement. Allergies are not a valid reason to refuse on the spot; if you have a medical condition that conflicts with this obligation, contact support in advance. Violations may result in permanent deactivation.

## 12. Confidentiality of Rider data

You will receive limited personal information about Riders (name, pickup and drop-off locations, and sometimes a masked phone number). You may use it only to complete the trip. You must not store, copy, share or use it for any other purpose, contact Riders after the trip, or disclose it to anyone, except as required by law. This obligation continues after this Agreement ends.

## 13. Deactivation and appeal

We may suspend or deactivate your account for breach of this Agreement, our policies or the law; for loss of eligibility (for example, expired insurance, an ineligible background check result or licence suspension); for fraud; or for safety reasons. Where appropriate, we will give you notice and reasons. You may appeal by opening a support ticket or emailing {{ support_email }} within 30 days; a reviewer not involved in the original decision will consider your appeal. You may end this Agreement at any time by deactivating your driver profile.

## 14. Liability and indemnity

You are solely responsible for your vehicle, your driving and your conduct, and for complying with all laws and licensing requirements. To the extent permitted by law, you will indemnify and hold harmless NegoRide and its officers, employees and agents from claims, losses and expenses arising from your breach of this Agreement, your violation of law, or your negligence or wilful misconduct. NegoRide's liability to you is limited as set out in the Terms & Conditions. **[REVIEW WITH COUNSEL]**

## 15. Changes

We may amend this Agreement by giving you at least 30 days' notice in the app, except for changes required by law or for safety, which may take effect sooner. If you do not agree, you may stop using the Platform. Continuing to drive after the effective time means you accept the change.

## 16. Governing law

This Agreement is governed by the laws of the Province of Ontario and the federal laws of Canada applicable therein. **[REVIEW WITH COUNSEL]** — consider mandatory application of local law for drivers in Québec and other provinces.

## 17. Language

This Agreement is available in English and French; both versions are equally authoritative. The parties have expressly required that this Agreement be drawn up in both languages.

## 18. Contact

{{ company_legal_name }}, {{ company_address }} — {{ support_email }} — {{ website }}
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

Le présent Contrat du chauffeur (le « Contrat ») est conclu entre vous, la personne qui demande à offrir des services au moyen de la Plateforme NegoRide (« vous » ou le « Chauffeur »), et {{ company_legal_name }}, {{ company_address }} (« NegoRide » ou « nous »). Il complète nos Conditions d’utilisation, notre Politique de confidentialité, nos Lignes directrices de la communauté, notre Politique d’annulation et de remboursement, notre Politique de sécurité et notre Avis sur l’enregistrement audio, qui s’appliquent aussi à vous. En cas de conflit, le présent Contrat régit votre relation avec nous en tant que Chauffeur.

## 1. Statut d’entrepreneur indépendant

Vous êtes un entrepreneur indépendant. Vous n’êtes ni un employé, ni un mandataire, ni un associé, ni un franchisé de NegoRide. **[À RÉVISER PAR UN AVOCAT]** — examiner au regard des normes du travail provinciales (p. ex. la *Loi de 2022 sur les droits des travailleurs de plateformes numériques* de l’Ontario) et adapter les avis en conséquence.

- Vous décidez si, quand, où et pendant combien de temps vous vous connectez, et quelles demandes de course, négociations ou réservations de places vous acceptez.
- Vous êtes libre d’utiliser d’autres plateformes ou d’exploiter votre propre entreprise en même temps.
- Vous fournissez et entretenez à vos frais votre véhicule, votre téléphone, votre forfait de données, votre carburant et tout autre équipement.
- NegoRide ne contrôle pas la façon dont vous effectuez une course, sauf pour exiger le respect de la loi, des règles de sécurité et de nos politiques.
- Vous n’avez pas droit aux avantages sociaux des employés, et NegoRide ne retient pas d’impôt sur le revenu ni de cotisations au RPC/RRQ ou à l’assurance-emploi sur vos gains, sauf si la loi l’exige.

## 2. Admissibilité

Pour conduire avec NegoRide, vous devez en tout temps :

- avoir au moins **{{ min_driver_age }}** ans;
- être titulaire d’un permis de conduire complet et valide (ni probatoire, ni progressif) de la province où vous conduisez, de la classe exigée pour le service offert;
- avoir le droit de travailler au Canada;
- conduire un véhicule de l’année **{{ min_vehicle_year }}** ou plus récent, sécuritaire, propre et immatriculé, comptant quatre portes (pour le transport de passagers) et ayant réussi toute inspection exigée par votre province ou votre municipalité;
- détenir une assurance automobile valide pour le véhicule, **y compris un avenant pour le covoiturage commercial ou le transport rémunéré lorsque votre province ou votre assureur l’exige**, ainsi que tout permis municipal de transport rémunéré requis là où vous exercez vos activités. **[À RÉVISER PAR UN AVOCAT]** — confirmer, province par province, les exigences d’assurance et de permis, et déterminer si NegoRide souscrira une police de flotte couvrant les périodes de course;
- réussir notre processus d’intégration : vérification du numéro de téléphone, examen des documents, vérification des antécédents par Certn, examen par un administrateur et séance d’orientation sur la sécurité.

## 3. Documents et validité

Vous devez téléverser votre permis de conduire, le certificat d’immatriculation, la preuve d’assurance, des photos du véhicule et un égoportrait pour la vérification d’identité, et les garder à jour et exacts. Nous vous enverrons des rappels avant l’expiration des documents. **Vous ne pouvez pas vous mettre en ligne si des documents sont expirés ou manquants**; votre compte sera automatiquement mis en pause jusqu’à l’approbation de documents à jour. Vous devez nous aviser dans les 48 heures de tout changement touchant votre permis (y compris une suspension, une nouvelle déclaration de culpabilité ou des points d’inaptitude qui ont une incidence sur votre admissibilité), votre assurance ou votre véhicule.

## 4. Vérification des antécédents

Avec votre consentement exprès et distinct (voir le Consentement à la vérification des antécédents), NegoRide obtiendra une vérification des antécédents par l’entremise de Certn, comprenant une vérification du casier judiciaire canadien, une vérification d’identité et un dossier de conduite. Les frais de vérification sont à votre charge. La vérification est refaite **tous les {{ recheck_months }} mois**, et nous pouvons demander une nouvelle vérification en tout temps si nous recevons des renseignements indiquant que votre admissibilité pourrait avoir changé, lorsque la loi le permet. Les décisions seront prises de façon équitable et conforme aux lois sur les droits de la personne, en tenant compte du lien entre tout antécédent et le travail. **[À RÉVISER PAR UN AVOCAT]**

## 5. Tarifs, négociation et commission

- **Location avec chauffeur :** vous et le passager négociez un prix dans l’application. Une fois accepté par les deux parties, le prix convenu est définitif. Vous ne devez pas exiger d’argent supplémentaire, emprunter un trajet plus long ou ajouter des frais qui ne figurent pas dans l’application. Toute modification du prix exige l’accord des deux parties dans l’application.
- **Covoiturage :** vous fixez un prix par place pour les trajets que vous publiez, dans les limites que nous pouvons établir.
- **Commission :** NegoRide retient une commission de service de **{{ commission_pct }} %** sur chaque tarif (à l’exclusion des pourboires, que vous conservez en totalité). Le taux de commission peut changer moyennant un préavis d’au moins 30 jours dans l’application; le taux en vigueur au moment où une course est confirmée s’applique à cette course.
- Les frais d’attente, d’annulation et de non-présentation perçus en vertu de la Politique d’annulation et de remboursement vous sont versés, déduction faite de la commission, sauf disposition contraire de la politique.
- Vous ne devez jamais accepter d’argent comptant ou de paiement hors application pour une course organisée au moyen de NegoRide.

## 6. Versements

Les versements sont effectués par **Stripe Connect**. Vous devez compléter la vérification d’identité de Stripe et fournir un compte bancaire canadien. Vos gains vous sont versés selon le calendrier indiqué dans l’application, une fois la course terminée et le paiement prélevé. Nous pouvons retenir un versement pendant l’examen d’un différend, d’une rétrofacturation, d’une fraude ou d’un incident de sécurité, et déduire de vos gains les sommes dues aux passagers (par exemple, le remboursement d’un trop-perçu) ou à NegoRide. Vous recevrez des relevés de gains dans l’application.

## 7. Impôts et taxes

**Vous êtes responsable de vos propres impôts et taxes**, y compris l’impôt sur le revenu tiré de vos gains et toute obligation de vous inscrire aux fins de la TPS/TVH (et de la TVQ au Québec), de percevoir ces taxes et de les verser. Selon les règles fédérales actuelles, les chauffeurs qui offrent des services de taxi ou de covoiturage commercial doivent généralement s’inscrire aux fins de la TPS/TVH dès leur première course, même si leurs revenus sont inférieurs au seuil de 30 000 $ applicable aux petits fournisseurs pour la plupart des autres entreprises. **[À RÉVISER PAR UN AVOCAT]** — confirmer le traitement applicable à la Location avec chauffeur, au Covoiturage, à la messagerie et au déménagement, et déterminer si NegoRide perçoit et verse les taxes pour le compte des chauffeurs. Nous vous fournirons un sommaire annuel de vos gains et pourrions être tenus de déclarer vos gains à l’Agence du revenu du Canada ou à Revenu Québec en vertu des règles de déclaration applicables aux plateformes numériques.

## 8. Annulations, non-présentations et manquements de fiabilité

Les passagers comptent sur vous une fois la course confirmée. Un **manquement de fiabilité** vous est attribué lorsque vous annulez après la confirmation (sauf pour un motif de sécurité valable ou un manquement du passager aux Lignes directrices de la communauté), ou lorsque vous n’arrivez pas avant l’heure d’arrivée prévue majorée du délai de grâce prévu à la Politique d’annulation et de remboursement (non-présentation du chauffeur).

- Plus de **{{ strikes_warn_after }}** manquements en **{{ strikes_window_days }}** jours entraînent un **avertissement**.
- Plus de **{{ strikes_suspend_after }}** manquements en **{{ strikes_window_days }}** jours entraînent une **suspension temporaire de {{ strikes_suspend_days }} jours**.
- Des suspensions répétées peuvent entraîner une désactivation.

Vous pouvez contester un manquement au moyen d’un billet de soutien si vous croyez qu’il a été attribué par erreur (par exemple, si le passager vous a demandé d’annuler ou si vous avez annulé pour des raisons de sécurité).

## 9. Évaluations

Les passagers vous évaluent après chaque course, et vous les évaluez aussi. Votre note correspond à la moyenne de vos courses récentes évaluées. Si votre note descend sous le minimum indiqué dans l’application, nous vous en avertirons et vous proposerons des ressources pour vous améliorer. Si elle demeure sous ce minimum, nous pouvons suspendre ou désactiver votre compte. Les évaluations que nous jugeons discriminatoires ou faites par représailles seront exclues.

## 10. Obligations en matière de sécurité

Vous vous engagez à :

- respecter le code de la route et ne jamais conduire avec les facultés affaiblies, fatigué ou distrait (aucune utilisation du téléphone tenu en main pendant la conduite);
- vérifier le NIP de course avant de commencer une course et vous assurer que tous les passagers bouclent leur ceinture;
- garder votre véhicule sécuritaire et bien entretenu, y compris des pneus d’hiver lorsque la loi l’exige;
- prendre des pauses raisonnables et ne pas conduire plus d’heures qu’il n’est sécuritaire de le faire (voir la Politique de sécurité);
- signaler immédiatement dans l’application tout accident, blessure ou incident de sécurité et collaborer avec notre équipe de sécurité;
- suivre notre séance d’orientation sur la sécurité et toute formation d’appoint que nous exigeons.

Vous pouvez signaler un passager, mettre fin à une course ou la refuser si vous vous sentez en danger; utilisez le bouton SOS ou composez le 911 en cas d’urgence.

## 11. Non-discrimination et animaux d’assistance

Vous ne devez faire preuve d’aucune discrimination envers un passager pour un motif protégé par les lois sur les droits de la personne, y compris dans la négociation, l’acceptation, l’annulation ou l’évaluation. **Vous devez accepter les passagers accompagnés d’un animal d’assistance** — c’est une obligation légale. Les allergies ne constituent pas un motif valable de refus sur place; si vous avez un problème de santé incompatible avec cette obligation, communiquez avec le soutien à l’avance. Toute violation peut entraîner une désactivation définitive.

## 12. Confidentialité des renseignements des passagers

Vous recevez des renseignements personnels limités sur les passagers (nom, lieux de prise en charge et de dépôt et, parfois, un numéro de téléphone masqué). Vous ne pouvez les utiliser que pour effectuer la course. Vous ne devez pas les conserver, les copier, les partager ou les utiliser à d’autres fins, communiquer avec des passagers après la course ni les divulguer à quiconque, sauf si la loi l’exige. Cette obligation subsiste après la fin du présent Contrat.

## 13. Désactivation et contestation

Nous pouvons suspendre ou désactiver votre compte en cas de manquement au présent Contrat, à nos politiques ou à la loi; en cas de perte d’admissibilité (par exemple, une assurance expirée, un résultat de vérification des antécédents non admissible ou une suspension de permis); en cas de fraude; ou pour des raisons de sécurité. Lorsqu’il y a lieu, nous vous en aviserons et vous en indiquerons les motifs. Vous pouvez contester la décision en ouvrant un billet de soutien ou en écrivant à {{ support_email }} dans les 30 jours; une personne qui n’a pas participé à la décision initiale examinera votre contestation. Vous pouvez mettre fin au présent Contrat en tout temps en désactivant votre profil de chauffeur.

## 14. Responsabilité et indemnisation

Vous êtes seul responsable de votre véhicule, de votre conduite et de votre comportement, ainsi que du respect de toutes les lois et exigences en matière de permis. Dans la mesure permise par la loi, vous vous engagez à indemniser NegoRide ainsi que ses dirigeants, employés et mandataires et à les tenir indemnes de toute réclamation, perte ou dépense découlant de votre manquement au présent Contrat, d’une infraction à la loi ou de votre négligence ou inconduite volontaire. La responsabilité de NegoRide envers vous est limitée comme le prévoient les Conditions d’utilisation. **[À RÉVISER PAR UN AVOCAT]**

## 15. Modifications

Nous pouvons modifier le présent Contrat moyennant un préavis d’au moins 30 jours dans l’application, sauf pour les modifications exigées par la loi ou pour des raisons de sécurité, qui peuvent entrer en vigueur plus tôt. Si vous ne les acceptez pas, vous pouvez cesser d’utiliser la Plateforme. Si vous continuez de conduire après leur entrée en vigueur, vous acceptez les modifications.

## 16. Droit applicable

Le présent Contrat est régi par les lois de la province d’Ontario et les lois fédérales du Canada qui s’y appliquent. **[À RÉVISER PAR UN AVOCAT]** — évaluer l’application impérative du droit local pour les chauffeurs du Québec et des autres provinces.

## 17. Langue

Le présent Contrat est offert en français et en anglais; les deux versions font également foi. Les parties ont expressément exigé que le présent Contrat soit rédigé dans les deux langues.

## 18. Nous joindre

{{ company_legal_name }}, {{ company_address }} — {{ support_email }} — {{ website }}
""",
        },
    },
    # ------------------------------------------------------------------
    # 5. Cancellation & Refund Policy
    # (all figures come from live app settings via Jinja variables)
    # ------------------------------------------------------------------
    {
        'type': 'cancellation_policy',
        'audience': 'all',
        'title': {
            'en': 'Cancellation & Refund Policy',
            'fr': 'Politique d’annulation et de remboursement',
        },
        'summary': {
            'en': """- Car Hire: cancelling within {{ free_window_min }} minutes of confirming is free, and your card hold is released.
- After that, while the driver is on the way, the fee is {{ cancel_fee }} or {{ cancel_fee_pct_cap }}% of the fare, whichever is lower.
- If your driver cancels or doesn't show up, you pay nothing. A driver no-show also earns you a {{ driver_credit }} ride credit.
- Rideshare seats: full refund more than {{ rideshare_refund_full_h }} hours before departure, {{ rideshare_refund_half_pct }}% between {{ rideshare_refund_half_h }} and {{ rideshare_refund_full_h }} hours, none after that.
- Holds are released right away. Refunds reach your card in 5–10 business days.
- You can dispute a charge within 72 hours through the app.
""",
            'fr': """- Location avec chauffeur : l’annulation dans les {{ free_window_min }} minutes suivant la confirmation est gratuite, et la retenue sur votre carte est libérée.
- Ensuite, pendant que le chauffeur est en route, les frais sont de {{ cancel_fee }} ou de {{ cancel_fee_pct_cap }} % du tarif, selon le montant le moins élevé.
- Si votre chauffeur annule ou ne se présente pas, vous ne payez rien. Une non-présentation du chauffeur vous donne aussi droit à un crédit de course de {{ driver_credit }}.
- Places en Covoiturage : remboursement complet plus de {{ rideshare_refund_full_h }} heures avant le départ, {{ rideshare_refund_half_pct }} % entre {{ rideshare_refund_half_h }} et {{ rideshare_refund_full_h }} heures, aucun remboursement ensuite.
- Les retenues sont libérées immédiatement. Les remboursements apparaissent sur votre carte dans un délai de 5 à 10 jours ouvrables.
- Vous pouvez contester un débit dans les 72 heures au moyen de l’application.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

This Cancellation & Refund Policy forms part of the Terms & Conditions of {{ company_legal_name }} ("NegoRide"). The amounts and time limits below are taken directly from the settings the app uses to calculate charges, so the figures you see here are the ones that apply. The version in force when you confirm a trip applies to that trip. All amounts are in Canadian dollars and include any applicable taxes shown in the app.

## 1. Car Hire (on-demand negotiated rides)

For Car Hire, once you and the driver agree on a price, we place a temporary hold on your card before the driver heads to you. The hold is captured (charged) only when the trip is completed. "Confirmation" means the moment the agreed price is accepted and the hold succeeds.

| Situation | What you pay |
|---|---|
| You cancel before payment is authorized or before a driver is on the way | Nothing |
| You cancel within {{ free_window_min }} minutes after confirmation | Nothing — the hold is released |
| You cancel later, while the driver is en route | {{ cancel_fee }} or {{ cancel_fee_pct_cap }}% of the agreed fare, whichever is lower |
| You cancel after the driver has arrived | {{ after_arrival_fee }}, plus waiting time after the first {{ wait_free_min }} free minutes at {{ wait_rate_per_min }} per minute |
| You don't show up after the driver has waited {{ wait_window_min }} minutes | {{ noshow_fee }} (no-show fee) |
| The driver cancels after confirmation | Nothing — full release of the hold; the driver receives a reliability strike |
| The driver doesn't arrive by the ETA plus {{ driver_no_show_grace_min }} minutes (driver no-show) | Nothing — full refund, plus a {{ driver_credit }} ride credit |
| Trip ended early for safety reasons | Reviewed by our safety team; you pay a pro-rated amount or nothing |

**Waiting time.** Once the driver marks that they have arrived at the pickup point, the first {{ wait_free_min }} minutes of waiting are free. After that, waiting time is charged at {{ wait_rate_per_min }} per minute and added to the fare. The driver may mark you as a no-show after waiting {{ wait_window_min }} minutes and trying to contact you through the app.

**Valid reasons for a free cancellation.** We will waive the fee on request if the driver's vehicle or licence plate does not match the app, the driver asks you to cancel, the driver asks for more than the agreed price or for an off-app payment, the driver is clearly heading away from you, or the driver does not have a child car seat you requested in advance. Report this through the trip's Help option.

## 2. Rideshare seats (scheduled journeys)

Seats on published Rideshare journeys are charged when you book. Refunds depend on how far ahead of the scheduled departure you cancel.

| When you cancel | Refund |
|---|---|
| More than {{ rideshare_refund_full_h }} hours before departure | 100% |
| Between {{ rideshare_refund_half_h }} and {{ rideshare_refund_full_h }} hours before departure | {{ rideshare_refund_half_pct }}% |
| Less than {{ rideshare_refund_half_h }} hours before departure, or no-show | 0% |
| The driver cancels the journey | 100% to every passenger |

If the driver changes the departure time or route significantly after you book, you may cancel for a full refund.

## 3. Driver reliability strikes

Drivers who cancel after confirmation, or who fail to arrive (driver no-show), receive a reliability strike. More than {{ strikes_warn_after }} strikes within {{ strikes_window_days }} days results in a warning, and more than {{ strikes_suspend_after }} strikes within {{ strikes_window_days }} days results in a temporary suspension of {{ strikes_suspend_days }} days. Drivers may dispute a strike through a support ticket. See the Driver Agreement for details.

## 4. Refund timing

- **Holds** that are released (for example, a free cancellation) are released immediately on our side. Your bank may take a few days to remove the pending amount from your statement.
- **Refunds** of amounts already charged are sent to your original payment method and usually appear within 5–10 business days, depending on your bank.
- **Ride credits** are added to your NegoRide account immediately and applied automatically to your next eligible trip. Credits have no cash value. **[REVIEW WITH COUNSEL]** — confirm expiry rules for credits under provincial gift-card / prepaid-purchase laws.

## 5. Background check fee (drivers)

The background check fee paid by driver applicants is **non-refundable once your check has been submitted to Certn**, because the screening work begins immediately. If you cancel your application before the check is submitted, the fee will be refunded in full.

## 6. Disputes

If you believe a fee was charged in error, open a dispute from the trip's Help option **within 72 hours** of the trip. Our team will review trip data (timestamps, GPS and in-app messages) and respond, usually within a few business days. Nothing in this policy limits your rights under applicable consumer protection legislation, including your right to contact your card issuer. **[REVIEW WITH COUNSEL]**

## 7. Contact

Questions about a charge? Contact {{ support_email }} or visit {{ website }}.
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

La présente Politique d’annulation et de remboursement fait partie des Conditions d’utilisation de {{ company_legal_name }} (« NegoRide »). Les montants et délais ci-dessous proviennent directement des paramètres utilisés par l’application pour calculer les frais; les chiffres indiqués ici sont donc ceux qui s’appliquent. La version en vigueur au moment où vous confirmez une course s’applique à cette course. Tous les montants sont en dollars canadiens et comprennent les taxes applicables indiquées dans l’application.

## 1. Location avec chauffeur (courses sur demande à prix négocié)

En Location avec chauffeur, dès que vous et le chauffeur convenez d’un prix, nous plaçons une retenue temporaire sur votre carte avant que le chauffeur se mette en route vers vous. La retenue n’est prélevée (débitée) qu’à la fin de la course. La « confirmation » correspond au moment où le prix convenu est accepté et où la retenue est autorisée.

| Situation | Ce que vous payez |
|---|---|
| Vous annulez avant l’autorisation du paiement ou avant qu’un chauffeur soit en route | Rien |
| Vous annulez dans les {{ free_window_min }} minutes suivant la confirmation | Rien — la retenue est libérée |
| Vous annulez plus tard, pendant que le chauffeur est en route | {{ cancel_fee }} ou {{ cancel_fee_pct_cap }} % du tarif convenu, selon le montant le moins élevé |
| Vous annulez après l’arrivée du chauffeur | {{ after_arrival_fee }}, plus le temps d’attente au-delà des {{ wait_free_min }} premières minutes gratuites, à {{ wait_rate_per_min }} la minute |
| Vous ne vous présentez pas après {{ wait_window_min }} minutes d’attente du chauffeur | {{ noshow_fee }} (frais de non-présentation) |
| Le chauffeur annule après la confirmation | Rien — libération complète de la retenue; le chauffeur reçoit un manquement de fiabilité |
| Le chauffeur n’arrive pas avant l’heure prévue plus {{ driver_no_show_grace_min }} minutes (non-présentation du chauffeur) | Rien — remboursement complet, plus un crédit de course de {{ driver_credit }} |
| Course interrompue pour des raisons de sécurité | Examen par notre équipe de sécurité; vous payez un montant au prorata ou rien |

**Temps d’attente.** Dès que le chauffeur indique qu’il est arrivé au point de prise en charge, les {{ wait_free_min }} premières minutes d’attente sont gratuites. Ensuite, le temps d’attente est facturé à {{ wait_rate_per_min }} la minute et ajouté au tarif. Le chauffeur peut vous déclarer absent après avoir attendu {{ wait_window_min }} minutes et tenté de vous joindre au moyen de l’application.

**Motifs valables d’annulation gratuite.** Nous annulerons les frais sur demande si le véhicule ou la plaque d’immatriculation ne correspond pas à l’application, si le chauffeur vous demande d’annuler, s’il exige plus que le prix convenu ou un paiement hors application, s’il s’éloigne manifestement de vous, ou s’il n’a pas le siège d’auto pour enfant demandé à l’avance. Signalez-le au moyen de l’option Aide de la course.

## 2. Places en Covoiturage (trajets planifiés)

Les places sur les trajets de Covoiturage publiés sont débitées au moment de la réservation. Le remboursement dépend du moment de votre annulation par rapport au départ prévu.

| Moment de l’annulation | Remboursement |
|---|---|
| Plus de {{ rideshare_refund_full_h }} heures avant le départ | 100 % |
| Entre {{ rideshare_refund_half_h }} et {{ rideshare_refund_full_h }} heures avant le départ | {{ rideshare_refund_half_pct }} % |
| Moins de {{ rideshare_refund_half_h }} heures avant le départ, ou non-présentation | 0 % |
| Le chauffeur annule le trajet | 100 % à chaque passager |

Si le chauffeur modifie de façon importante l’heure de départ ou l’itinéraire après votre réservation, vous pouvez annuler et obtenir un remboursement complet.

## 3. Manquements de fiabilité des chauffeurs

Le chauffeur qui annule après la confirmation, ou qui ne se présente pas, reçoit un manquement de fiabilité. Plus de {{ strikes_warn_after }} manquements en {{ strikes_window_days }} jours entraînent un avertissement, et plus de {{ strikes_suspend_after }} manquements en {{ strikes_window_days }} jours entraînent une suspension temporaire de {{ strikes_suspend_days }} jours. Le chauffeur peut contester un manquement au moyen d’un billet de soutien. Pour en savoir plus, consultez le Contrat du chauffeur.

## 4. Délais de remboursement

- **Les retenues** libérées (par exemple, lors d’une annulation gratuite) le sont immédiatement de notre côté. Votre institution financière peut prendre quelques jours pour retirer le montant en attente de votre relevé.
- **Les remboursements** de sommes déjà débitées sont versés sur votre mode de paiement initial et apparaissent généralement dans un délai de 5 à 10 jours ouvrables, selon votre institution financière.
- **Les crédits de course** sont ajoutés immédiatement à votre compte NegoRide et appliqués automatiquement à votre prochaine course admissible. Les crédits n’ont aucune valeur monétaire. **[À RÉVISER PAR UN AVOCAT]** — confirmer les règles d’expiration des crédits au regard des lois provinciales sur les cartes-cadeaux et les contrats de prépaiement.

## 5. Frais de vérification des antécédents (chauffeurs)

Les frais de vérification des antécédents payés par les candidats chauffeurs sont **non remboursables une fois la vérification soumise à Certn**, puisque le travail de vérification commence immédiatement. Si vous annulez votre demande avant la soumission de la vérification, les frais vous seront remboursés en totalité.

## 6. Contestations

Si vous croyez qu’un montant vous a été facturé par erreur, ouvrez une contestation à partir de l’option Aide de la course **dans les 72 heures** suivant celle-ci. Notre équipe examinera les données de la course (horodatage, GPS et messages dans l’application) et vous répondra, habituellement en quelques jours ouvrables. Rien dans la présente politique ne limite les droits que vous confèrent les lois applicables sur la protection du consommateur, y compris votre droit de communiquer avec l’émetteur de votre carte. **[À RÉVISER PAR UN AVOCAT]**

## 7. Nous joindre

Des questions sur un débit? Écrivez à {{ support_email }} ou visitez {{ website }}.
""",
        },
    },
    # ------------------------------------------------------------------
    # 6. Safety Policy
    # ------------------------------------------------------------------
    {
        'type': 'safety_policy',
        'audience': 'all',
        'title': {
            'en': 'Safety Policy',
            'fr': 'Politique de sécurité',
        },
        'summary': {
            'en': """- In an emergency, call 911 first. NegoRide is not an emergency service.
- The SOS button connects you to our 24/7 safety team and shares your live location with them.
- Check the driver, the car and the licence plate, then give the 4-digit ride PIN. Only then should the trip start.
- Share your trip with trusted contacts. The link stops working when the trip ends.
- We check for unexpected route changes, and you can turn on audio recording if you want it.
- Drivers can flag riders too. Everyone can report an incident from the app.
""",
            'fr': """- En cas d’urgence, composez d’abord le 911. NegoRide n’est pas un service d’urgence.
- Le bouton SOS vous met en contact avec notre équipe de sécurité, disponible 24 heures sur 24, 7 jours sur 7, et lui transmet votre position en temps réel.
- Vérifiez le chauffeur, le véhicule et la plaque d’immatriculation, puis donnez le NIP de course à 4 chiffres. La course ne doit commencer qu’à ce moment.
- Partagez votre trajet avec des contacts de confiance. Le lien cesse de fonctionner à la fin de la course.
- Nous surveillons les changements d’itinéraire inattendus, et vous pouvez activer l’enregistrement audio si vous le souhaitez.
- Les chauffeurs peuvent aussi signaler des passagers. Tout le monde peut signaler un incident à partir de l’application.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

Safety is at the heart of everything {{ company_legal_name }} ("NegoRide") builds. This Safety Policy explains the tools we provide, what we expect from Riders and Drivers, and how we respond when something goes wrong. It forms part of our Terms & Conditions and should be read with our Community Guidelines and Audio Recording Notice.

## 1. Emergencies: call 911

**NegoRide is not an emergency service.** If you or anyone else is in immediate danger, is injured, or witnesses a crime, **call 911 right away**. The app has a 911 button that dials emergency services directly from your phone and shows your current location and trip details on screen so you can read them to the dispatcher. **[REVIEW WITH COUNSEL]** — do not represent that location is transmitted automatically to 911 unless integrated with a certified provider.

## 2. SOS button and the safety team

The SOS button is available during every trip. When you press it:

- NegoRide's safety team, available 24/7, is alerted immediately with your live location, trip details, and the other party's details;
- a safety agent will try to contact you through the app;
- if we cannot reach you and believe there is a risk to someone's life or safety, we may contact emergency services on your behalf.

SOS supplements, and does not replace, calling 911. Misusing SOS may lead to account action.

## 3. Ride PIN and vehicle verification

Before getting in, Riders should check that the Driver's name, photo, vehicle make, model, colour and **licence plate** match the app. Each Car Hire trip has a 4-digit **ride PIN**. The Rider gives the PIN to the Driver only once they have confirmed the vehicle; the Driver enters it to start the trip. Drivers must not start a trip without the correct PIN. Never get into a vehicle that does not match — cancel and report it.

## 4. Trusted contacts and live trip sharing

You can add trusted contacts and share a live link to your trip showing the Driver's details, vehicle, route and estimated arrival. The public link expires automatically when the trip ends. You can also set up automatic sharing for trips at night or for every trip.

## 5. Route-deviation checks

During trips we monitor for unexpected events, such as a long unexplained stop or a significant departure from the expected route. When we detect one, we may send both parties a check-in asking whether everything is okay, with quick access to SOS and 911. If there is no response, our safety team may follow up.

## 6. Audio recording

Riders and Drivers may choose to turn on in-trip audio recording. The other party is shown an indicator when recording is active. Recordings are encrypted, stored privately, accessed only by trained safety reviewers for safety and dispute purposes, and automatically deleted after {{ recording_retention_days }} days unless linked to an incident or dispute. Full details are in the Audio Recording Notice.

## 7. Driver safety

Drivers deserve to feel safe too. Drivers can see a Rider's rating before accepting, can end a trip if they feel unsafe, and can **flag a Rider** for our safety team to review. Drivers have access to the same SOS and 911 tools. Riders who threaten, assault or harass Drivers will be permanently removed.

## 8. Reporting incidents

Anyone can report a safety incident, accident, lost item or concern from the trip's Help option, or by emailing {{ support_email }}. We review reports promptly, prioritizing the most serious. We may temporarily restrict an account while we investigate. We will not tell the other party who reported them where that could create a safety risk, and we prohibit retaliation against anyone who reports in good faith.

## 9. Zero tolerance

We have zero tolerance for violence, sexual misconduct, threats, weapons, impaired driving, and discrimination. Confirmed violations lead to permanent removal from the Platform and, where appropriate, reporting to police. See the Community Guidelines.

## 10. Law-enforcement requests

We cooperate with law enforcement in accordance with the law. We disclose personal information to police only in response to a valid legal process (such as a production order or warrant), or without one where permitted by law — for example, in an emergency that threatens someone's life, health or security. We review every request, disclose only what is necessary, and keep a record of each disclosure. **[REVIEW WITH COUNSEL]**

## 11. Vehicle safety and maintenance

Drivers must keep their vehicles safe, clean and mechanically sound, with working seat belts, lights, brakes and tires, and complete any inspections required by their province or municipality. Drivers must use winter tires where required by law (for example, in Québec in winter) and keep an emergency kit in the vehicle. We may ask for updated vehicle photos or proof of inspection.

## 12. Fatigue

Tired driving is dangerous driving. Drivers should take regular breaks and never drive when drowsy. We may require Drivers to go offline for a rest period after a long stretch of continuous online time. **[REVIEW WITH COUNSEL]** — set maximum driving hours per 24-hour period and required rest in line with provincial guidance.

## 13. Weather and road conditions

Canadian weather can change quickly. Drivers may decline or end a trip, and Riders may cancel without a fee, when road conditions are unsafe (for example, during a severe winter storm or road-closure warning). Drivers must adjust their driving to conditions. For Rideshare journeys, Drivers should notify passengers in the app of any weather-related delay or cancellation.

## 14. Contact

For non-emergency safety questions, contact {{ support_email }}. In an emergency, call 911.
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

La sécurité est au cœur de tout ce que {{ company_legal_name }} (« NegoRide ») conçoit. La présente Politique de sécurité décrit les outils que nous offrons, ce que nous attendons des passagers et des chauffeurs, et la façon dont nous intervenons en cas de problème. Elle fait partie de nos Conditions d’utilisation et doit être lue avec nos Lignes directrices de la communauté et notre Avis sur l’enregistrement audio.

## 1. Urgences : composez le 911

**NegoRide n’est pas un service d’urgence.** Si vous ou une autre personne êtes en danger immédiat, êtes blessé ou êtes témoin d’un crime, **composez le 911 sans tarder**. L’application comporte un bouton 911 qui compose directement le numéro des services d’urgence à partir de votre téléphone et affiche à l’écran votre position actuelle et les détails de la course afin que vous puissiez les lire au répartiteur. **[À RÉVISER PAR UN AVOCAT]** — ne pas laisser entendre que la position est transmise automatiquement au 911, sauf intégration avec un fournisseur certifié.

## 2. Bouton SOS et équipe de sécurité

Le bouton SOS est accessible pendant chaque course. Lorsque vous l’activez :

- l’équipe de sécurité de NegoRide, disponible 24 heures sur 24, 7 jours sur 7, est immédiatement alertée et reçoit votre position en temps réel, les détails de la course et les renseignements sur l’autre partie;
- un agent de sécurité tentera de communiquer avec vous au moyen de l’application;
- si nous ne pouvons pas vous joindre et que nous croyons que la vie ou la sécurité d’une personne est menacée, nous pouvons communiquer avec les services d’urgence en votre nom.

Le bouton SOS complète l’appel au 911, mais ne le remplace pas. L’utilisation abusive du bouton SOS peut entraîner des mesures visant votre compte.

## 3. NIP de course et vérification du véhicule

Avant de monter, le passager devrait vérifier que le nom et la photo du chauffeur, ainsi que la marque, le modèle, la couleur et la **plaque d’immatriculation** du véhicule, correspondent à l’application. Chaque course en Location avec chauffeur comporte un **NIP de course** à 4 chiffres. Le passager ne donne le NIP au chauffeur qu’une fois le véhicule confirmé; le chauffeur l’entre pour commencer la course. Le chauffeur ne doit pas commencer une course sans le bon NIP. Ne montez jamais dans un véhicule qui ne correspond pas — annulez la course et signalez-le.

## 4. Contacts de confiance et partage du trajet en temps réel

Vous pouvez ajouter des contacts de confiance et partager un lien en temps réel vers votre course, qui indique les renseignements sur le chauffeur, le véhicule, l’itinéraire et l’heure d’arrivée prévue. Le lien public expire automatiquement à la fin de la course. Vous pouvez aussi activer le partage automatique pour les courses de nuit ou pour toutes vos courses.

## 5. Détection des écarts d’itinéraire

Pendant les courses, nous surveillons les événements inattendus, comme un long arrêt inexpliqué ou un écart important par rapport à l’itinéraire prévu. Lorsque nous en détectons un, nous pouvons envoyer aux deux parties une vérification leur demandant si tout va bien, avec un accès rapide au bouton SOS et au 911. En l’absence de réponse, notre équipe de sécurité peut faire un suivi.

## 6. Enregistrement audio

Les passagers et les chauffeurs peuvent choisir d’activer l’enregistrement audio pendant la course. Un indicateur s’affiche pour l’autre partie lorsque l’enregistrement est en cours. Les enregistrements sont chiffrés, conservés de façon confidentielle, consultés uniquement par des analystes de la sécurité formés, à des fins de sécurité et de règlement des différends, et supprimés automatiquement après {{ recording_retention_days }} jours, sauf s’ils sont liés à un incident ou à un différend. Tous les détails figurent dans l’Avis sur l’enregistrement audio.

## 7. Sécurité des chauffeurs

Les chauffeurs ont eux aussi le droit de se sentir en sécurité. Ils peuvent voir l’évaluation d’un passager avant d’accepter une course, mettre fin à une course s’ils se sentent en danger et **signaler un passager** à notre équipe de sécurité. Les chauffeurs ont accès aux mêmes outils SOS et 911. Les passagers qui menacent, agressent ou harcèlent un chauffeur seront retirés définitivement de la Plateforme.

## 8. Signalement des incidents

Toute personne peut signaler un incident de sécurité, un accident, un objet perdu ou une préoccupation à partir de l’option Aide de la course, ou en écrivant à {{ support_email }}. Nous examinons les signalements rapidement, en priorisant les plus graves. Nous pouvons restreindre temporairement un compte pendant l’enquête. Nous ne révélons pas à l’autre partie l’identité de la personne qui a fait le signalement lorsque cela pourrait compromettre sa sécurité, et nous interdisons toute forme de représailles contre une personne qui signale un incident de bonne foi.

## 9. Tolérance zéro

Nous appliquons une tolérance zéro envers la violence, l’inconduite sexuelle, les menaces, les armes, la conduite avec facultés affaiblies et la discrimination. Toute violation confirmée entraîne le retrait définitif de la Plateforme et, lorsqu’il y a lieu, un signalement à la police. Consultez les Lignes directrices de la communauté.

## 10. Demandes des forces de l’ordre

Nous collaborons avec les forces de l’ordre conformément à la loi. Nous communiquons des renseignements personnels à la police uniquement en réponse à une procédure judiciaire valide (comme une ordonnance de communication ou un mandat) ou, sans celle-ci, lorsque la loi le permet — par exemple, en cas d’urgence menaçant la vie, la santé ou la sécurité d’une personne. Nous examinons chaque demande, ne communiquons que ce qui est nécessaire et consignons chaque communication. **[À RÉVISER PAR UN AVOCAT]**

## 11. Sécurité et entretien des véhicules

Les chauffeurs doivent garder leur véhicule sécuritaire, propre et en bon état mécanique, avec des ceintures de sécurité, des phares, des freins et des pneus en bon état, et se soumettre à toute inspection exigée par leur province ou leur municipalité. Ils doivent utiliser des pneus d’hiver lorsque la loi l’exige (par exemple, au Québec pendant l’hiver) et garder une trousse d’urgence dans le véhicule. Nous pouvons demander des photos à jour du véhicule ou une preuve d’inspection.

## 12. Fatigue

Conduire fatigué, c’est conduire dangereusement. Les chauffeurs devraient prendre des pauses régulières et ne jamais conduire lorsqu’ils sont somnolents. Nous pouvons exiger qu’un chauffeur se mette hors ligne pour une période de repos après une longue période continue en ligne. **[À RÉVISER PAR UN AVOCAT]** — fixer le nombre maximal d’heures de conduite par période de 24 heures et le repos obligatoire, conformément aux recommandations provinciales.

## 13. Météo et conditions routières

Au Canada, la météo peut changer rapidement. Le chauffeur peut refuser ou interrompre une course, et le passager peut annuler sans frais, lorsque les conditions routières sont dangereuses (par exemple, lors d’une forte tempête hivernale ou d’un avis de fermeture de route). Le chauffeur doit adapter sa conduite aux conditions. Pour les trajets de Covoiturage, le chauffeur devrait aviser les passagers dans l’application de tout retard ou de toute annulation liés à la météo.

## 14. Nous joindre

Pour toute question de sécurité non urgente, écrivez à {{ support_email }}. En cas d’urgence, composez le 911.
""",
        },
    },
    # ------------------------------------------------------------------
    # 7. Audio Recording Notice
    # ------------------------------------------------------------------
    {
        'type': 'recording_notice',
        'audience': 'all',
        'title': {
            'en': 'Audio Recording Notice',
            'fr': 'Avis sur l’enregistrement audio',
        },
        'summary': {
            'en': """- Audio recording during a trip is optional. It only happens if you or the other person turns it on.
- The other person always sees an indicator when recording is on, and everyone agrees to this notice as part of the Terms.
- Recordings are encrypted and used only for safety and dispute resolution. Only trained safety reviewers can listen, and every access is logged.
- Recordings are deleted after {{ recording_retention_days }} days unless they are linked to a report or dispute.
- You can't download the other person's audio. Police get it only with a lawful request or in an emergency.
""",
            'fr': """- L’enregistrement audio pendant la course est facultatif. Il n’a lieu que si vous ou l’autre personne l’activez.
- L’autre personne voit toujours un indicateur lorsque l’enregistrement est en cours, et tout le monde accepte le présent avis dans le cadre des Conditions d’utilisation.
- Les enregistrements sont chiffrés et servent uniquement à la sécurité et au règlement des différends. Seuls des analystes de la sécurité formés peuvent les écouter, et chaque accès est consigné.
- Les enregistrements sont supprimés après {{ recording_retention_days }} jours, sauf s’ils sont liés à un signalement ou à un différend.
- Vous ne pouvez pas télécharger l’enregistrement de l’autre personne. La police n’y a accès qu’en vertu d’une demande légale ou en cas d’urgence.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

This notice explains how optional in-trip audio recording works on the NegoRide Platform operated by {{ company_legal_name }} ("NegoRide"). It forms part of our Terms & Conditions and Privacy Policy, which every Rider and Driver accepts before using the Platform.

## 1. Recording is optional

Audio recording is an **opt-in** safety feature. It is off by default. A Rider or a Driver may turn it on for a single trip or for all their trips from the app's safety settings. No one is required to use it, and not using it has no effect on your account, ratings or access to trips.

## 2. Both parties are informed

We believe safety tools work best when they are transparent:

- When recording is active, **the other party sees a clear recording indicator** in their app for the duration of the trip.
- This notice is part of the Terms & Conditions that **both Riders and Drivers accept** before using the Platform, so everyone knows that trips may be recorded.
- Drivers may also display a sticker in the vehicle indicating that audio recording may be in use. **[REVIEW WITH COUNSEL]**

## 3. What is recorded and why

When turned on, the app records audio through the phone's microphone from the start of the trip until it ends. It does not record video. Recordings are used **only** for:

- investigating safety incidents and reports;
- resolving disputes between Riders and Drivers (for example, about the agreed price, conduct or damage);
- responding to lawful requests as described below.

We do not use recordings for marketing, advertising, profiling, performance monitoring unrelated to a report, or training artificial-intelligence models.

## 4. Legal basis

We collect and use recordings in accordance with PIPEDA and Québec's *Act respecting the protection of personal information in the private sector* (Law 25). Recording is enabled by the user's express, opt-in choice, and all users are informed through this notice and the in-app indicator. Under section 184 of the *Criminal Code*, intercepting a private communication is lawful where one of the parties to the communication consents; the person who turns on recording is a party to the conversation. **[REVIEW WITH COUNSEL]** — confirm one-party consent analysis, conversations with third parties (e.g., phone calls taken by a passenger), and any provincial or municipal restrictions on recording in vehicles for hire.

## 5. Storage and security

Recordings are uploaded over an encrypted connection and **stored encrypted** in private storage that is not publicly accessible. Storage may be located in Canada or the United States. **[REVIEW WITH COUNSEL]** — confirm hosting region and document the cross-border assessment required by Law 25.

## 6. Who can access recordings

- Only **trained members of our safety team** can listen to a recording, and only when it is linked to a report, incident or dispute.
- **Every access is logged** (who, when and why), and logs are reviewed regularly.
- **Users cannot download or listen to the other party's recording.** This protects everyone's privacy and prevents misuse.

## 7. Retention

- Recordings not linked to any report, incident or dispute are **automatically deleted after {{ recording_retention_days }} days**.
- If a recording is linked to an incident, report or dispute, it is kept until the case is closed and then for **{{ recording_hold_after_case_days }} more days**, after which it is deleted, unless we are legally required to keep it longer (for example, under a preservation order).

## 8. Disclosure to police and others

We disclose recordings to law enforcement **only** in response to a valid legal request (such as a production order or warrant), or where we believe in good faith that disclosure is necessary to prevent imminent harm to someone's life, health or security. We may also disclose a recording to our legal advisers or insurers where necessary to handle a claim. We record every disclosure.

## 9. Your rights

You may request access to personal information about you, including recordings you made or in which you appear, by writing to our Privacy Officer at {{ support_email }}. We will review requests case by case and may need to withhold or edit parts of a recording to protect the privacy of others, as permitted by law. You may also ask us to delete a recording you made, unless it is linked to an open case.

## 10. How to turn it off

You can turn audio recording off at any time from **Settings > Safety > Audio recording**, or during a trip from the safety toolkit. Stopping a recording during a trip ends recording from that moment; audio already captured is handled as described above.

## 11. Contact

Questions? Contact {{ support_email }} or visit {{ website }}.
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

Le présent avis explique le fonctionnement de l’enregistrement audio facultatif pendant la course sur la Plateforme NegoRide exploitée par {{ company_legal_name }} (« NegoRide »). Il fait partie de nos Conditions d’utilisation et de notre Politique de confidentialité, que chaque passager et chaque chauffeur accepte avant d’utiliser la Plateforme.

## 1. L’enregistrement est facultatif

L’enregistrement audio est une fonction de sécurité **à activer soi-même**. Elle est désactivée par défaut. Un passager ou un chauffeur peut l’activer pour une seule course ou pour toutes ses courses à partir des paramètres de sécurité de l’application. Personne n’est tenu de l’utiliser, et ne pas l’utiliser n’a aucune incidence sur votre compte, vos évaluations ou votre accès aux courses.

## 2. Les deux parties sont informées

Nous croyons que les outils de sécurité fonctionnent mieux lorsqu’ils sont transparents :

- Lorsque l’enregistrement est en cours, **l’autre partie voit un indicateur d’enregistrement bien visible** dans son application pendant toute la course.
- Le présent avis fait partie des Conditions d’utilisation que **les passagers et les chauffeurs acceptent** avant d’utiliser la Plateforme; tout le monde sait donc que les courses peuvent être enregistrées.
- Les chauffeurs peuvent aussi apposer dans leur véhicule un autocollant indiquant qu’un enregistrement audio peut avoir lieu. **[À RÉVISER PAR UN AVOCAT]**

## 3. Ce qui est enregistré et pourquoi

Lorsque la fonction est activée, l’application enregistre le son au moyen du microphone du téléphone, du début à la fin de la course. Aucune vidéo n’est enregistrée. Les enregistrements servent **uniquement** à :

- enquêter sur les incidents et les signalements de sécurité;
- régler les différends entre passagers et chauffeurs (par exemple, au sujet du prix convenu, du comportement ou de dommages);
- répondre aux demandes légales décrites ci-dessous.

Nous n’utilisons pas les enregistrements à des fins de marketing, de publicité, de profilage, de suivi du rendement sans lien avec un signalement, ni pour entraîner des modèles d’intelligence artificielle.

## 4. Fondement juridique

Nous recueillons et utilisons les enregistrements conformément à la LPRPDE et à la *Loi sur la protection des renseignements personnels dans le secteur privé* du Québec (Loi 25). L’enregistrement repose sur le choix exprès de l’utilisateur de l’activer, et tous les utilisateurs en sont informés par le présent avis et par l’indicateur affiché dans l’application. En vertu de l’article 184 du *Code criminel*, l’interception d’une communication privée est légale lorsque l’une des parties à la communication y consent; la personne qui active l’enregistrement est partie à la conversation. **[À RÉVISER PAR UN AVOCAT]** — confirmer l’analyse du consentement d’une seule partie, le cas des conversations avec des tiers (p. ex. un appel téléphonique pris par un passager) et toute restriction provinciale ou municipale sur l’enregistrement dans les véhicules de transport rémunéré.

## 5. Stockage et sécurité

Les enregistrements sont téléversés au moyen d’une connexion chiffrée et **conservés sous forme chiffrée** dans un espace de stockage privé qui n’est pas accessible au public. Le stockage peut se trouver au Canada ou aux États-Unis. **[À RÉVISER PAR UN AVOCAT]** — confirmer la région d’hébergement et documenter l’évaluation préalable à la communication hors Québec exigée par la Loi 25.

## 6. Qui peut accéder aux enregistrements

- Seuls les **membres formés de notre équipe de sécurité** peuvent écouter un enregistrement, et uniquement lorsqu’il est lié à un signalement, à un incident ou à un différend.
- **Chaque accès est consigné** (qui, quand et pourquoi), et les journaux sont examinés régulièrement.
- **Les utilisateurs ne peuvent ni télécharger ni écouter l’enregistrement fait par l’autre partie.** Cette règle protège la vie privée de chacun et prévient les abus.

## 7. Conservation

- Les enregistrements qui ne sont liés à aucun signalement, incident ou différend sont **supprimés automatiquement après {{ recording_retention_days }} jours**.
- Si un enregistrement est lié à un incident, à un signalement ou à un différend, il est conservé jusqu’à la clôture du dossier, puis pendant **{{ recording_hold_after_case_days }} jours supplémentaires**, après quoi il est supprimé, à moins que la loi ne nous oblige à le conserver plus longtemps (par exemple, en vertu d’une ordonnance de conservation).

## 8. Communication à la police et à d’autres personnes

Nous communiquons des enregistrements aux forces de l’ordre **uniquement** en réponse à une demande légale valide (comme une ordonnance de communication ou un mandat), ou lorsque nous croyons de bonne foi que la communication est nécessaire pour prévenir un préjudice imminent à la vie, à la santé ou à la sécurité d’une personne. Nous pouvons aussi communiquer un enregistrement à nos conseillers juridiques ou à nos assureurs lorsque c’est nécessaire pour traiter une réclamation. Nous consignons chaque communication.

## 9. Vos droits

Vous pouvez demander l’accès aux renseignements personnels vous concernant, y compris les enregistrements que vous avez faits ou dans lesquels on entend votre voix, en écrivant à notre responsable de la protection des renseignements personnels à {{ support_email }}. Nous examinerons chaque demande au cas par cas et pourrions devoir retenir ou masquer des parties d’un enregistrement pour protéger la vie privée d’autres personnes, comme le permet la loi. Vous pouvez aussi nous demander de supprimer un enregistrement que vous avez fait, sauf s’il est lié à un dossier ouvert.

## 10. Comment désactiver l’enregistrement

Vous pouvez désactiver l’enregistrement audio en tout temps dans **Paramètres > Sécurité > Enregistrement audio**, ou pendant une course au moyen de la trousse de sécurité. L’arrêt de l’enregistrement pendant une course y met fin à partir de ce moment; le son déjà capté est traité comme décrit ci-dessus.

## 11. Nous joindre

Des questions? Écrivez à {{ support_email }} ou visitez {{ website }}.
""",
        },
    },
    # ------------------------------------------------------------------
    # 8. Background Check Disclosure & Consent
    # ------------------------------------------------------------------
    {
        'type': 'background_check_consent',
        'audience': 'driver',
        'title': {
            'en': 'Background Check Disclosure & Consent',
            'fr': 'Avis et consentement relatifs à la vérification des antécédents',
        },
        'summary': {
            'en': """- Certn, a third-party screening company, runs your background check for {{ company_legal_name }}.
- The check covers a Canadian criminal record check, identity verification and your driver's abstract.
- The fee is {{ bgc_fee }}, and you pay it. It is non-refundable once your check is submitted to Certn, and refunded if you cancel before that.
- Checks are repeated every {{ recheck_months }} months while you drive with us.
- You can get a copy of your report and dispute anything that is wrong.
- You sign by typing your full legal name. If you withdraw consent, your application ends.
""",
            'fr': """- Certn, une entreprise de vérification indépendante, effectue votre vérification des antécédents pour le compte de {{ company_legal_name }}.
- La vérification comprend une vérification du casier judiciaire canadien, une vérification d’identité et votre dossier de conduite.
- Les frais sont de {{ bgc_fee }} et sont à votre charge. Ils ne sont pas remboursables une fois la vérification soumise à Certn, mais ils sont remboursés si vous annulez avant.
- La vérification est refaite tous les {{ recheck_months }} mois tant que vous conduisez avec nous.
- Vous pouvez obtenir une copie de votre rapport et contester tout renseignement inexact.
- Vous signez en tapant votre nom légal complet. Si vous retirez votre consentement, votre demande prend fin.
""",
        },
        'body': {
            'en': """> Draft v1.0 — prepared for review by legal counsel before launch.

## 1. Disclosure

As part of your application to offer services as a Driver on the NegoRide Platform, {{ company_legal_name }} ("NegoRide"), {{ company_address }}, will obtain a background check about you. The check is conducted on NegoRide's behalf by **Certn**, a third-party consumer reporting and background screening agency. This document is provided separately from our other terms so that you can make an informed decision. **[REVIEW WITH COUNSEL]** — confirm whether Certn's own disclosure and consent forms satisfy all provincial requirements, or whether this form must be supplemented.

## 2. What is checked

The background check may include:

- a **Canadian criminal record check**, searched against national RCMP databases (the Canadian Police Information Centre), which may include a check of self-declared records and, where required, a vulnerable-sector or fingerprint-based verification;
- **identity verification**, which may compare your government-issued photo ID with a selfie and check its authenticity;
- your **driver's abstract / motor vehicle record** from the provincial licensing authority, including licence status, class, convictions, demerit points and suspensions;
- where included in our screening package, **international sanctions and watchlist** searches. **[REVIEW WITH COUNSEL]** — confirm final Certn package contents.

We do not request credit reports as part of this check.

## 3. How your information is collected

You will be directed to a secure page hosted by Certn, where you enter your personal details (such as full legal name, previous names, date of birth, addresses and driver's licence number) and upload identity documents. Certn collects and processes this information under its own privacy policy and as our service provider. Certn may store and process information in Canada and, for certain services, outside Canada. **[REVIEW WITH COUNSEL]**

## 4. Fee

The background check fee is **{{ bgc_fee }}**, paid by you through the app.

- The fee is **non-refundable once your check has been submitted to Certn**, whatever the result.
- If you cancel your application **before** the check is submitted, the fee will be refunded in full.

## 5. Ongoing re-screening

While you remain an active Driver, NegoRide will ask Certn to repeat the check **every {{ recheck_months }} months**, and may request a new check sooner where permitted by law (for example, after receiving information that your eligibility may have changed). By consenting below, you authorize these periodic re-checks for as long as your driver account is active. We will notify you before each re-check; a fee may apply as shown in the app at that time.

## 6. How results are used

Certn will provide NegoRide with the results. Our trained team reviews them and classifies your application as:

- **Clear** — eligible to continue onboarding;
- **Needs review** — we will look at the nature, date and relevance of any record to driving and passenger safety, and may contact you to give you an opportunity to provide context before any decision is made;
- **Not eligible** — you cannot drive on the Platform. We will tell you, identify Certn as the agency that provided the report, and explain how to obtain a copy and dispute it.

Decisions will be made consistently with applicable human-rights laws, including protections relating to records for which a pardon or record suspension has been granted. **[REVIEW WITH COUNSEL]**

## 7. Your rights: copies and disputes

You have the right to receive a copy of your background report and to dispute any information you believe is inaccurate or incomplete:

- directly with Certn at {{ certn_dispute_contact }}; and
- with NegoRide at {{ support_email }}.

We will not make a final adverse decision based on information you have disputed until the dispute has been reviewed, where the law requires this.

## 8. Provincial consumer reporting laws

Several provinces regulate consumer reports, including Ontario's *Consumer Reporting Act*, which requires that you be informed before a consumer report containing personal information is obtained, that you be told if a decision is based wholly or partly on it, and of the name and address of the consumer reporting agency. Similar laws exist in other provinces (e.g., British Columbia, Nova Scotia, Manitoba, Saskatchewan). This disclosure is intended to meet those requirements. **[REVIEW WITH COUNSEL]**

## 9. Québec residents

If you reside in Québec, your information is collected, used and communicated in accordance with the *Act respecting the protection of personal information in the private sector*, and the communication of your information to Certn and any processing outside Québec is subject to the protections described in our Privacy Policy. Consent requests relating to criminal records must be specific to the position; the check is limited to information relevant to transporting members of the public. **[REVIEW WITH COUNSEL]** — confirm compliance with the Québec Charter of human rights and freedoms, s. 18.2.

## 10. Retention

NegoRide keeps your background check result (clear / needs review / not eligible), the date of the check and your consent record for as long as your driver account is active and afterwards for the period required by law or needed to defend legal claims. We do not keep a copy of the full report longer than necessary. Certn retains information under its own retention schedule.

## 11. Electronic signature

By typing your full legal name below and tapping "I consent", you confirm that:

- you have read and understood this disclosure;
- you authorize {{ company_legal_name }} and Certn to obtain the checks described above, now and periodically while you are an active Driver;
- the information you provide is true and complete;
- your typed name is your electronic signature and has the same legal effect as a handwritten signature.

## 12. Withdrawing consent

You may withdraw this consent at any time by contacting {{ support_email }}. If you withdraw consent, **your driver application or driver account will end**, because a current background check is a condition of driving on the Platform. Withdrawal does not affect checks already completed, and fees already paid for submitted checks are not refunded.
""",
            'fr': """> Ébauche v1.0 — préparée pour révision par un conseiller juridique avant le lancement.

## 1. Avis

Dans le cadre de votre demande pour offrir des services à titre de chauffeur sur la Plateforme NegoRide, {{ company_legal_name }} (« NegoRide »), {{ company_address }}, obtiendra une vérification de vos antécédents. Cette vérification est effectuée pour le compte de NegoRide par **Certn**, une agence indépendante de renseignements sur les consommateurs et de vérification des antécédents. Le présent document vous est remis séparément de nos autres conditions afin que vous puissiez prendre une décision éclairée. **[À RÉVISER PAR UN AVOCAT]** — confirmer si les formulaires d’avis et de consentement de Certn satisfont à toutes les exigences provinciales ou s’ils doivent être complétés par le présent formulaire.

## 2. Ce qui est vérifié

La vérification peut comprendre :

- une **vérification du casier judiciaire canadien**, effectuée dans les bases de données nationales de la GRC (Centre d’information de la police canadienne), qui peut comprendre une vérification des antécédents déclarés et, au besoin, une vérification pour le secteur vulnérable ou fondée sur les empreintes digitales;
- une **vérification d’identité**, qui peut comparer votre pièce d’identité avec photo délivrée par un gouvernement avec un égoportrait et en vérifier l’authenticité;
- votre **dossier de conduite** obtenu auprès de l’autorité provinciale responsable des permis, y compris l’état et la classe du permis, les déclarations de culpabilité, les points d’inaptitude et les suspensions;
- lorsqu’elles sont incluses dans notre forfait de vérification, des recherches dans les **listes de sanctions et de surveillance internationales**. **[À RÉVISER PAR UN AVOCAT]** — confirmer le contenu définitif du forfait Certn.

Nous ne demandons pas de dossier de crédit dans le cadre de cette vérification.

## 3. Collecte de vos renseignements

Vous serez dirigé vers une page sécurisée hébergée par Certn, où vous saisirez vos renseignements personnels (comme votre nom légal complet, vos noms antérieurs, votre date de naissance, vos adresses et votre numéro de permis de conduire) et téléverserez vos pièces d’identité. Certn recueille et traite ces renseignements conformément à sa propre politique de confidentialité et à titre de fournisseur de services. Certn peut conserver et traiter des renseignements au Canada et, pour certains services, à l’extérieur du Canada. **[À RÉVISER PAR UN AVOCAT]**

## 4. Frais

Les frais de vérification des antécédents sont de **{{ bgc_fee }}** et sont payés par vous au moyen de l’application.

- Les frais sont **non remboursables une fois la vérification soumise à Certn**, quel qu’en soit le résultat.
- Si vous annulez votre demande **avant** la soumission de la vérification, les frais vous seront remboursés en totalité.

## 5. Vérifications périodiques

Tant que vous demeurez un chauffeur actif, NegoRide demandera à Certn de refaire la vérification **tous les {{ recheck_months }} mois**, et pourra demander une nouvelle vérification plus tôt lorsque la loi le permet (par exemple, après avoir reçu des renseignements indiquant que votre admissibilité pourrait avoir changé). En donnant votre consentement ci-dessous, vous autorisez ces vérifications périodiques tant que votre compte chauffeur est actif. Nous vous aviserons avant chaque nouvelle vérification; des frais peuvent s’appliquer, comme indiqué dans l’application à ce moment.

## 6. Utilisation des résultats

Certn transmettra les résultats à NegoRide. Notre équipe formée les examine et classe votre demande comme suit :

- **Conforme** — vous êtes admissible à poursuivre l’intégration;
- **Examen requis** — nous tiendrons compte de la nature, de la date et de la pertinence de tout antécédent pour la conduite et la sécurité des passagers, et nous pourrions communiquer avec vous pour vous permettre de fournir des explications avant toute décision;
- **Non admissible** — vous ne pouvez pas conduire sur la Plateforme. Nous vous en informerons, nous vous indiquerons que Certn est l’agence qui a fourni le rapport et nous vous expliquerons comment en obtenir une copie et le contester.

Les décisions seront prises conformément aux lois applicables sur les droits de la personne, y compris les protections relatives aux antécédents ayant fait l’objet d’un pardon ou d’une suspension du casier. **[À RÉVISER PAR UN AVOCAT]**

## 7. Vos droits : copie et contestation

Vous avez le droit de recevoir une copie de votre rapport de vérification et de contester tout renseignement que vous croyez inexact ou incomplet :

- directement auprès de Certn, à {{ certn_dispute_contact }};
- auprès de NegoRide, à {{ support_email }}.

Lorsque la loi l’exige, nous ne prendrons aucune décision défavorable définitive fondée sur un renseignement que vous avez contesté avant que la contestation ait été examinée.

## 8. Lois provinciales sur les renseignements sur les consommateurs

Plusieurs provinces encadrent les rapports de solvabilité et de renseignements sur les consommateurs, notamment l’Ontario avec la *Loi sur les renseignements concernant le consommateur*, qui exige que vous soyez informé avant l’obtention d’un rapport contenant des renseignements personnels, que vous soyez avisé si une décision est fondée en tout ou en partie sur ce rapport, et que l’on vous communique le nom et l’adresse de l’agence de renseignements. Des lois semblables existent dans d’autres provinces (p. ex. la Colombie-Britannique, la Nouvelle-Écosse, le Manitoba et la Saskatchewan). Le présent avis vise à satisfaire à ces exigences. **[À RÉVISER PAR UN AVOCAT]**

## 9. Résidents du Québec

Si vous résidez au Québec, vos renseignements sont recueillis, utilisés et communiqués conformément à la *Loi sur la protection des renseignements personnels dans le secteur privé*, et leur communication à Certn ainsi que tout traitement à l’extérieur du Québec sont assujettis aux protections décrites dans notre Politique de confidentialité. Toute demande de consentement visant les antécédents judiciaires doit être propre au poste; la vérification se limite aux renseignements pertinents pour le transport de membres du public. **[À RÉVISER PAR UN AVOCAT]** — confirmer la conformité à l’article 18.2 de la Charte des droits et libertés de la personne du Québec.

## 10. Conservation

NegoRide conserve le résultat de votre vérification (conforme / examen requis / non admissible), la date de la vérification et la preuve de votre consentement tant que votre compte chauffeur est actif, puis pendant la période exigée par la loi ou nécessaire pour faire valoir ses droits en justice. Nous ne conservons pas de copie du rapport complet plus longtemps que nécessaire. Certn conserve les renseignements selon son propre calendrier de conservation.

## 11. Signature électronique

En tapant votre nom légal complet ci-dessous et en touchant « Je consens », vous confirmez que :

- vous avez lu et compris le présent avis;
- vous autorisez {{ company_legal_name }} et Certn à obtenir les vérifications décrites ci-dessus, maintenant et périodiquement tant que vous êtes un chauffeur actif;
- les renseignements que vous fournissez sont véridiques et complets;
- votre nom tapé constitue votre signature électronique et a le même effet juridique qu’une signature manuscrite.

## 12. Retrait du consentement

Vous pouvez retirer le présent consentement en tout temps en écrivant à {{ support_email }}. Si vous retirez votre consentement, **votre demande ou votre compte chauffeur prendra fin**, puisqu’une vérification des antécédents à jour est une condition pour conduire sur la Plateforme. Le retrait n’a aucun effet sur les vérifications déjà effectuées, et les frais déjà payés pour des vérifications soumises ne sont pas remboursés.
""",
        },
    },
]
