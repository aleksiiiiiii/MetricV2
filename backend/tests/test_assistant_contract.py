"""Le contrat élargi de l'assistant : actions, tranches demandées, titre (`IA-14`).

**Tout ce fichier tourne sans réseau et sans application.** `conversation.py` est un module
pur : une consigne à assembler, une réponse à relire. C'est ce qui permet de couvrir ici
les cas qu'un modèle rend une fois sur cent — un objet là où on attend une liste, un nom
inventé, quinze actions d'un coup — sans dépendre de ce qu'un modèle gratuit aura décidé
de faire ce jour-là.

Ce que ce fichier **ne** couvre pas : qu'une action nommée existe, que ses arguments soient
les bons, qu'elle soit permise. C'est l'affaire de l'exécuteur, qui connaît le catalogue.
La séparation est volontaire et c'est elle qui garde ce module pur.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.domains.assistant.conversation import (
    build_prompt,
    read_actions,
    read_need,
    read_title,
)
from app.domains.assistant.schemas import MAX_ACTIONS, MAX_NEED

CONTEXT = ["Nous sommes le vendredi 07/08/2026", "Séances par semaine : 1,8"]
MEMORY = ["blessure — Genou droit sensible"]

CATALOGUE = [
    "weight.add — noter une pesée. args : date (AAAA-MM-JJ), weight_kg (nombre)",
    "meal.add — noter un repas. args : meal_type, protein_g",
]
#: Des lignes **déjà décrites**, comme le catalogue au-dessus : depuis que les tranches
#: portent ce qu'elles rendent, `build_prompt` en reçoit du texte tout fait et non des noms.
SLICES = [
    "exercises — je te donne le catalogue des exercices",
    "meals.today — je te donne les repas d'une journée",
]

#: Les **noms** seuls, qui sont ce que `read_need` filtre. Séparés des lignes ci-dessus
#: depuis que les tranches portent une description : la consigne reçoit du texte rendu, le
#: filtre reçoit des clés. Les confondre marchait tant que les deux se ressemblaient.
SLICE_NAMES = ["exercises", "meals.today"]


def prompt(**kwargs: Any) -> str:
    base: dict[str, Any] = {"question": "Où j'en suis ?", "context": CONTEXT, "memory": MEMORY}
    return build_prompt(**{**base, **kwargs})


# ── 1. La consigne n'invite à agir que si c'est possible ──


def test_without_a_catalogue_the_prompt_never_mentions_actions() -> None:
    """C'est le comportement voulu, pas une commodité de test.

    Inviter à agir sans rien d'exécutable ne produirait que des promesses — « je l'ai
    ajouté » sans que rien ne soit écrit est pire que « je ne sais pas faire ».
    """
    text = prompt()

    assert '"actions"' not in text
    assert '"need"' not in text
    assert "Ce que tu peux faire" not in text


def test_the_catalogue_is_inserted_verbatim() -> None:
    """Le module ne connaît aucun nom d'action : il insère ce que le catalogue a rendu.

    C'est ce qui garde `conversation.py` pur, et le catalogue seul autorité sur ce qui
    existe. Un nom qui change ne se retrouve donc jamais à deux endroits.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    for line in CATALOGUE:
        assert line in text
    # Les tranches sont insérées de la même façon : lignes déjà rendues, une par tranche.
    # Ce module ne connaît donc pas plus un nom de tranche qu'un nom d'action.
    for line in SLICES:
        assert line in text


def test_the_prompt_presents_the_empty_list_as_the_normal_case() -> None:
    """Un modèle à qui on offre une possibilité la prend.

    Sans cette insistance, chaque « où j'en suis ? » repartirait avec une séance ajoutée.
    C'est le garde-fou le moins cher et le plus efficace du lot.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "Liste vide le plus" in text
    assert "une question est une question, pas une instruction" in text


def test_the_medical_guard_forbids_acting_not_only_advising() -> None:
    """`IA-12` s'étend : un assistant qui peut écrire ne doit pas agir sur une douleur.

    La consigne interdisait déjà de diagnostiquer. Elle doit maintenant interdire de
    *réagir* — créer une semaine de repos parce qu'on lui a parlé d'un genou serait une
    prescription déguisée en mise à jour de planning.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "Aucune action à la suite d'une douleur" in text


def test_the_title_is_only_asked_when_a_thread_opens() -> None:
    """Le redemander à chaque tour inviterait le modèle à rebaptiser une discussion."""
    assert '"title"' in prompt(naming=True)
    assert '"title"' not in prompt()


# ── 2. Les actions relues ─────────────────────────────


def test_a_well_formed_action_comes_back() -> None:
    actions = read_actions({"actions": [{"name": "weight.add", "args": {"weight_kg": 82.4}}]})

    assert len(actions) == 1
    assert actions[0].name == "weight.add"
    assert actions[0].args == {"weight_kg": 82.4}


def test_an_answer_without_actions_yields_none() -> None:
    """Le cas normal, et de loin."""
    assert read_actions({"reply": "Tu tournes à 1,8 séance."}) == []


def test_a_single_object_is_accepted_where_a_list_was_asked() -> None:
    """Un modèle rend parfois un objet là où la consigne demande une liste.

    L'accepter coûte deux lignes ; le refuser coûterait l'action *et* l'appel qui l'a
    produite. Même tolérance que pour `remember`.
    """
    actions = read_actions({"actions": {"name": "water.add", "args": {"volume_ml": 500}}})

    assert [item.name for item in actions] == ["water.add"]


def test_an_action_without_a_name_is_dropped() -> None:
    """Sans nom, il n'y a rien à exécuter — et rien à refuser non plus."""
    assert read_actions({"actions": [{"args": {"weight_kg": 82.4}}]}) == []


def test_an_action_without_args_keeps_an_empty_dict() -> None:
    """L'exécuteur validera ; il ne doit pas avoir à distinguer « absent » de « vide »."""
    actions = read_actions({"actions": [{"name": "goal.create"}]})

    assert actions[0].args == {}


def test_args_that_are_not_an_object_become_an_empty_dict() -> None:
    """Une chaîne à la place des arguments est une réponse mal formée, pas une charge."""
    actions = read_actions({"actions": [{"name": "weight.add", "args": "82,4 kg"}]})

    assert actions[0].args == {}


def test_actions_are_bounded() -> None:
    """« Range mon mois » se traduit en cinquante actions.

    La borne est un garde-fou de sécurité plus que de coût : le tour où le modèle se
    trompe est exactement celui où on ne veut pas qu'il écrive vingt lignes.
    """
    # L'entrée se dérive de la borne : fabriquer un nombre fixe d'actions rendait ce test
    # vert par accident dès que la borne le dépassait, et il ne mesurait alors plus rien.
    many = [{"name": "weight.add", "args": {"n": index}} for index in range(MAX_ACTIONS + 5)]

    assert len(read_actions({"actions": many})) == MAX_ACTIONS


def test_a_malformed_entry_does_not_lose_the_others() -> None:
    """Une réponse à moitié bonne vaut mieux qu'un échange perdu."""
    actions = read_actions(
        {"actions": ["pas un objet", {"name": "water.add"}, 42, {"name": "meal.add"}]}
    )

    assert [item.name for item in actions] == ["water.add", "meal.add"]


# ── 3. Les tranches demandées (`IA-09`) ───────────────


def test_a_requested_slice_must_be_one_we_offered() -> None:
    """La garantie de `IA-09` : le modèle choisit **dans ce qu'on lui a dit pouvoir
    demander**, il ne nomme pas un fichier.

    Sans ce filtre, « need »: ["/etc/passwd"] ou ["tout"] deviendrait une lecture.
    """
    need = read_need({"need": ["exercises", "inventé", "meals.today"]}, available=SLICE_NAMES)

    assert [item.name for item in need] == ["exercises", "meals.today"]


def test_a_single_string_is_accepted_where_a_list_was_asked() -> None:
    assert [item.name for item in read_need({"need": "exercises"}, available=SLICE_NAMES)] == [
        "exercises"
    ]


def test_a_slice_asked_twice_is_only_read_once() -> None:
    need = read_need({"need": ["exercises", "exercises"]}, available=SLICE_NAMES)

    assert [item.name for item in need] == ["exercises"]


# ── 7. Les tranches datées (lot 12.B) ─────────────────


def test_a_slice_without_a_date_still_means_today() -> None:
    """Le cas d'avant ce lot, et de très loin le plus fréquent : il ne bouge pas."""
    need = read_need({"need": ["exercises"]}, available=SLICE_NAMES)

    assert need[0].day is None
    assert need[0].week is False


def test_a_slice_can_name_the_day_it_wants() -> None:
    """« Et mardi dernier ? » devient une question à laquelle l'assistant peut répondre."""
    need = read_need({"need": ["meals.today@2026-08-15"]}, available=SLICE_NAMES)

    assert need[0].name == "meals.today"
    assert need[0].day == dt.date(2026, 8, 15)
    assert need[0].week is False


def test_a_slice_can_name_a_whole_week() -> None:
    need = read_need({"need": ["meals.today@semaine-2026-08-12"]}, available=SLICE_NAMES)

    assert need[0].day == dt.date(2026, 8, 12)
    assert need[0].week is True


# ── 7 bis. Les tranches cherchées (lot Charges) ───────


def test_a_slice_can_carry_a_search_term() -> None:
    """Ce qui permet au modèle de demander l'orthographe exacte d'un exercice avant de
    fabriquer une séance Cadence — la seule chose qui décide de la démonstration."""
    need = read_need({"need": ["exercises:push up"]}, available=SLICE_NAMES)

    assert need[0].name == "exercises"
    assert need[0].query == "push up"
    assert need[0].day is None


def test_a_search_term_never_widens_what_can_be_read() -> None:
    """**La garantie de `IA-09` ne bouge pas d'un pouce**, pas plus qu'avec une date : le
    mot-clé varie, le nom reste choisi dans la liste fermée."""
    need = read_need({"need": ["inventé:push up", "/etc/passwd:x"]}, available=SLICE_NAMES)

    assert need == []


def test_a_day_and_a_search_term_can_be_asked_together() -> None:
    """L'ordre est `nom@jour:recherche`, et le découpage suit : la recherche est le dernier
    morceau et peut contenir n'importe quoi, y compris ce qui ressemble à une date."""
    need = read_need({"need": ["meals.today@2026-08-15:push up"]}, available=SLICE_NAMES)

    assert need[0].name == "meals.today"
    assert need[0].day == dt.date(2026, 8, 15)
    assert need[0].query == "push up"


def test_a_slice_without_a_search_term_carries_an_empty_one() -> None:
    """Le cas d'avant ce lot : rien ne change pour les douze tranches qui ne cherchent pas."""
    need = read_need({"need": ["exercises"]}, available=SLICE_NAMES)

    assert need[0].query == ""


def test_the_name_is_still_checked_against_the_closed_list() -> None:
    """**La garantie de `IA-09` ne bouge pas d'un pouce.** Seule la période est libre, et
    elle ne désigne aucun fichier : une date n'ouvre rien que le nom n'ouvrait déjà."""
    need = read_need(
        {"need": ["inventé@2026-08-15", "/etc/passwd@2026-08-15"]}, available=SLICE_NAMES
    )

    assert need == []


def test_an_unreadable_date_yields_no_slice_rather_than_today() -> None:
    """**Rien n'est deviné, et surtout pas un repli sur aujourd'hui.**

    Servir les chiffres du jour à qui a demandé le 15/08 attribuerait à cette date des
    mesures qui n'y ont pas eu lieu. C'est une valeur inventée, en pire : elle est datée.
    """
    need = read_need(
        {"need": ["meals.today@hier", "meals.today@2026-13-45"]}, available=SLICE_NAMES
    )

    assert need == []


def test_the_same_slice_on_two_days_is_two_requests() -> None:
    """Le dédoublonnage porte sur la demande entière, pas sur le seul nom — sinon
    « lundi et mardi » ne rendrait que lundi."""
    need = read_need(
        {"need": ["meals.today@2026-08-15", "meals.today@2026-08-16"]}, available=SLICE_NAMES
    )

    assert [item.day for item in need] == [dt.date(2026, 8, 15), dt.date(2026, 8, 16)]


def test_a_dated_slice_reads_legibly_in_a_step() -> None:
    """L'écran annonce « repas (15/08) », pas la syntaxe du contrat."""
    need = read_need({"need": ["meals.today@2026-08-15"]}, available=SLICE_NAMES)

    assert need[0].label == "meals.today (15/08)"


def test_requested_slices_are_bounded() -> None:
    """Au-delà, le modèle réclame le dossier entier — ce que `IA-09` interdit."""
    available = [f"tranche{index}" for index in range(10)]

    assert len(read_need({"need": available}, available=available)) == MAX_NEED


def test_no_need_at_all_is_the_normal_case() -> None:
    assert read_need({"reply": "…"}, available=SLICE_NAMES) == []


# ── 4. Le titre du fil ────────────────────────────────


def test_the_model_names_the_thread() -> None:
    assert read_title({"title": "Stagnation du développé couché"}, fallback="…") == (
        "Stagnation du développé couché"
    )


def test_an_empty_title_falls_back_to_the_question() -> None:
    """Un titre vide vaut moins que la question : c'est sur lui qu'on retrouve un fil."""
    assert read_title({"title": "   "}, fallback="Où j'en suis ?") == "Où j'en suis ?"


def test_a_missing_title_falls_back_too() -> None:
    assert read_title({}, fallback="Où j'en suis ?") == "Où j'en suis ?"


def test_a_title_is_bounded_and_collapsed() -> None:
    """Un titre sur trois lignes ne se lit pas dans une liste."""
    title = read_title({"title": "un  titre\nsur   plusieurs\nlignes " * 20}, fallback="…")

    assert "\n" not in title
    assert "  " not in title
    assert len(title) <= 80


# ── 5. Ce qui protège des modèles de raisonnement ─────


def test_the_provider_is_asked_for_json_not_only_the_model() -> None:
    """Le mode JSON du fournisseur, ajouté sur constat de panne (`IA-14`).

    La moitié des modèles gratuits du catalogue raisonnent à voix haute avant de répondre.
    Relevé sur `nemotron-3-ultra` : 3 788 caractères de « The user is asking… », tronqués
    par `max_tokens` **avant la moindre accolade** — une tentative brûlée, et un `503`
    quand les autres candidats étaient au quota.

    La consigne demandait déjà « uniquement un objet JSON » ; ce champ le dit au
    fournisseur, qui contraint le décodage au lieu d'espérer l'obéissance.
    """
    from app.domains.ai.client import OpenRouterClient

    client = OpenRouterClient(api_key="x", base_url="https://exemple.test")
    body = client.build_body("un-modele", instruction="i", prompt="p", max_tokens=900)

    assert body["response_format"] == {"type": "json_object"}


def test_the_assistant_leaves_room_for_a_model_that_thinks_aloud() -> None:
    """900 jetons suffisaient à `{reply, remember}` ; le contrat en porte cinq.

    La marge n'est pas pour la réponse, elle est pour le raisonnement qui la précède
    parfois. Tronquée en plein milieu, la réponse ne rend aucun JSON, donc rien du tout.

    **Depuis le lot 7, elle est aussi pour la réponse.** `MAX_REPLY` autorise un plan
    d'entraînement, et un plafond de jetons calculé pour « quatre phrases au plus »
    couperait exactement les réponses que ce lot cherche à obtenir. Le plancher est donc
    lié à `MAX_REPLY` et non à un nombre choisi une fois : trois caractères de français par
    jeton, et de la place pour les quatre autres champs du contrat.
    """
    from app.domains.ai.service import MAX_ATTEMPTS
    from app.domains.assistant.conversation import MAX_REPLY
    from app.domains.assistant.service import MAX_TOKENS

    assert MAX_TOKENS >= MAX_REPLY / 3
    # Et le budget de tentatives tient compte du quota : les modèles gratuits y tombent
    # souvent, et trois essais partaient parfois entièrement en quotas.
    assert MAX_ATTEMPTS >= 5


# ── 6. Le lot 7 : ce dont la consigne s'est défaite ───


def test_the_reply_length_follows_the_question_not_a_fixed_count() -> None:
    """« Quatre phrases au plus » venait de l'extraction et n'a jamais été rediscuté.

    C'est ce qui produisait un assistant qui rapporte : aucun plan d'entraînement ne tient
    en quatre phrases, donc il n'en proposait pas. La borne subsiste dans `MAX_REPLY`, où
    elle est vérifiable ; la consigne, elle, ne compte plus les phrases.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "quatre phrases" not in text
    assert "longueur suit ce que je demande" in text


def test_the_prompt_asks_for_a_recommendation_not_a_recap() -> None:
    """Le défaut laissé ouvert par le jalon 3 : la donnée est là, l'autorisation manquait.

    Sur « je charge combien lundi ? », l'assistant ouvrait par « je n'ai pas de charge
    prescrite pour lundi » avant de réciter un historique qu'on ne lui demandait pas.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "réponds par ce qu'il faut faire" in text
    assert "Rappeler l'historique puis me laisser conclure" in text


def test_the_medical_guard_outranks_the_call_to_conclude() -> None:
    """La seule exception, et elle est **écrite dans la règle** plutôt que sous-entendue.

    Inviter à conclure sans nommer l'exception rouvrirait `IA-12` par la porte du coaching :
    « quoi faire » sur une douleur au genou est exactement ce que le garde-fou interdit. Un
    modèle ne rapproche pas deux règles distantes de dix lignes ; celle-ci renvoie à l'autre.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "Cette règle ne vaut pas pour une douleur" in text
    assert "Aucune action à la suite d'une douleur" in text


def test_a_reply_never_outgrows_what_a_stored_message_holds() -> None:
    """Sinon le fil rejouerait un texte que personne n'a lu.

    `_append_messages` coupe à `MAX_CONTENT`. Une réponse plus longue serait affichée
    entière puis stockée amputée, et sa relecture trois semaines plus tard rendrait un
    autre texte — une valeur inventée par troncature, ce que le dépôt interdit ailleurs.
    """
    from app.domains.assistant.conversation import MAX_REPLY
    from app.domains.assistant.models import MAX_CONTENT

    assert MAX_REPLY <= MAX_CONTENT


def test_an_extraction_keeps_its_temperature_and_a_conversation_drops_it() -> None:
    """`None` **retire** le champ ; il ne l'envoie pas à zéro, ce qui serait l'inverse.

    Le réglage est arrivé pour qu'une photo d'assiette ne rende pas 32 g puis 41 g de
    protéines, et il tient toujours pour la cascade gratuite qui l'accepte. Appliqué à une
    conversation, il rend dix réponses quasi identiques à dix questions voisines.
    """
    from app.domains.ai.client import EXTRACTION_TEMPERATURE, OpenRouterClient

    client = OpenRouterClient(api_key="x", base_url="https://exemple.test")

    extraction = client.build_body("un-modele", instruction="i", prompt="p")
    assert extraction["temperature"] == EXTRACTION_TEMPERATURE

    conversation_body = client.build_body(
        "un-modele", instruction="i", prompt="p", temperature=None
    )
    assert "temperature" not in conversation_body


def test_the_prompt_says_what_filling_need_actually_triggers() -> None:
    """Il disait **quoi** demander, jamais ce que ça déclenche.

    Quand `need` est rempli, la passe est rejouée et son `reply` est intégralement
    remplacé — il n'est même pas diffusé, puisque le serveur refuse de montrer une passe
    remplaçable. Le modèle rédigeait donc une réponse complète que personne ne verrait
    jamais : depuis que la consigne autorise un plan à se développer, c'est jusqu'à treize
    cents jetons produits pour rien à chaque question qui réclame une tranche.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "je te repose la question avec" in text
    assert "ne sera pas montrée" in text
    assert 'une seule phrase dans "reply"' in text


def test_the_prompt_names_the_ceiling_instead_of_dropping_silently() -> None:
    """« Demande tout d'un coup » sans nombre invite à en demander six, dont deux tombent
    en silence. Le chiffre vient de `MAX_NEED` plutôt que d'être recopié — deux sources
    divergeraient au premier réglage."""
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert f"en demander {MAX_NEED} au plus" in text


# ── 7 ter. Le dernier tour se déclare (log du 01/09) ──


def test_the_final_pass_never_offers_need_at_all() -> None:
    """**Le défaut, tel qu'il s'est produit.** Les deux passes recevaient la consigne au
    mot près. Le modèle relisait donc « je vais chercher ces tranches et je te repose la
    question », redemandait une tranche au dernier tour — où plus rien ne lit `need`
    (`IA-16`) — et écrivait une réponse d'attente en conséquence : « je vérifie le nom
    exact du reverse crunch, puis je crée ta séance ». C'est cette phrase-là qui
    s'affichait, deux fois de suite, sur une séance jamais créée.

    Une case absente est la façon la plus courte de dire qu'il n'y a plus rien à demander.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES, final=True)

    assert '"need"' not in text
    assert "je te repose la question avec" not in text


def test_the_final_pass_says_it_is_the_last_and_forbids_announcing() -> None:
    """« Je vérifie puis je crée » ne crée rien. Le dire là où le modèle le lit vaut mieux
    que de l'espérer."""
    text = prompt(actions=CATALOGUE, slices=SLICES, final=True)

    assert "dernier tour" in text
    assert "N'annonce rien que tu ne fasses dans ce même message" in text


def test_the_first_pass_still_invites_the_model_to_ask() -> None:
    """Le correctif ne doit pas retirer à la première passe ce qui la fait marcher : c'est
    là, et là seulement, que demander a un sens."""
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert 'remplis "need"' in text
    assert "dernier tour" not in text


def test_the_first_pass_says_to_ask_for_everything_at_once() -> None:
    """Le modèle ne peut pas savoir de quels mots-clés il aura besoin avant d'avoir choisi
    la séance — et c'est précisément à ce moment-là qu'il est trop tard. La consigne le
    dit donc avant."""
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "seule occasion" in text


# ── 8. Ce qu'un vrai dialogue a fait ressortir ────────


def test_a_missing_number_sends_the_model_looking_not_apologising() -> None:
    """**Le défaut le plus cher du dialogue relu : un tour entier perdu.**

    Sur « hier j'ai fait une super course », le modèle a répondu « je n'ai pas les chiffres
    précis dans ce que tu m'as donné » — alors que `activites_recentes` était dans sa
    liste. Il a fallu lui dire « demande la dernière course » pour qu'il aille la chercher.

    La cause était dans la consigne, pas dans le modèle : « si la réponse demande une
    donnée absente, dis-le » avait été écrit quand les tranches étaient pauvres, et
    poussait à s'excuser là où il fallait demander.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert 'demande-la dans "need" au lieu de t\'en excuser' in text
    assert "aucune tranche ne peut l'apporter" in text


def test_the_two_rules_about_missing_data_point_the_same_way() -> None:
    """Les règles d'action disaient « demande-le dans "reply", ou remplis "need" » —
    l'ordre inverse de celui qu'on vient de poser. Deux règles qui se contredisent laissent
    le modèle choisir, et il choisit la plus facile."""
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert 'laisse "actions" vide et **remplis "need"**' in text
    # Et la règle de base reste autonome : sans catalogue, « need » n'existe pas, et lui en
    # parler enverrait le modèle remplir un champ qu'on ne lui a pas donné.
    assert '"need"' not in prompt()


def test_a_greeting_gets_a_greeting_not_a_file_reading() -> None:
    """« heyy » rendait cinq métriques, un taux de respect à 33,3 %, un rappel médical et
    trois questions. La règle disait que la longueur suit la demande ; elle ne disait rien
    du cas où l'on ne demande **rien**."""
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "un bonjour\n  appelle un bonjour" in text
    assert "ne récite pas mon dossier" in text


def test_the_model_is_told_not_to_narrate_its_own_plumbing() -> None:
    """« J'ai déjà cette info sans avoir besoin de la redemander » — il venait de la
    chercher. « Dans ce que tu m'as donné » désigne un condensé dont l'utilisateur n'a pas
    à connaître l'existence."""
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "ne me décris pas ta mécanique" in text
    assert "j'ai déjà cette info" in text


def test_one_question_at_a_time_and_no_nagging() -> None:
    """Ce qui rend un coach mécanique au-delà des trois défauts : il posait trois questions
    d'affilée et rappelait à **chaque** message ce qui n'était pas noté."""
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "Une seule question à la fin, jamais trois" in text
    assert "répété on cesse de l'entendre" in text


def test_the_model_may_not_declare_data_absent_from_the_app() -> None:
    """**Le défaut le plus grave relevé en usage, et il est pire qu'un tour perdu.**

    « Cette course n'apparaît pas encore dans ton suivi » — elle y était. Le modèle n'a pas
    seulement omis de réclamer la tranche : il a affirmé une absence sur des données qu'il
    n'avait pas regardées. C'est une phrase fausse sur les données de quelqu'un, et
    l'utilisateur n'a aucun moyen de savoir qu'elle est fausse.

    Le condensé est **ce qu'on lui a montré**, pas tout ce que l'application garde. La
    distinction n'était écrite nulle part.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "Ne déclare jamais qu'une donnée n'est pas enregistrée" in text
    assert "pas tout ce que je garde" in text
