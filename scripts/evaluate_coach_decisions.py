"""Évalue des décisions V1 sur des cas de référence et des variantes inédites."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from neurocoach.bootstrap import build_coach_runtime
from neurocoach.config import Settings

CASES = {
    "bibliotheque": (
        "Je travaille en bibliothèque et je voudrais un petit complément de revenu. "
        "Je ne sais pas quelle idée choisir. J'ai deux soirées libres et pas de budget.",
        "Au travail j'aide souvent les lecteurs à retrouver des livres dans le catalogue. "
        "Je n'ai jamais animé de formation. Qu'est-ce que je pourrais essayer ?",
        "Je ne peux pas solliciter les lecteurs de la bibliothèque ni utiliser leurs données. "
        "Comment faire un premier essai seule ce soir ?",
    ),
    "plantes": (
        "Je rempote régulièrement mes plantes d'intérieur et celles de ma voisine. "
        "J'aimerais en tirer un petit revenu, sans me déplacer ni acheter de stock. "
        "Que puis-je proposer ?",
        "Je ne sais pas reconnaître les maladies des plantes et je n'ai encore aucun client. "
        "Quel essai concret puis-je faire ce week-end ?",
        "J'ai essayé sur un pothos et je me suis aperçue que je n'ai pas toujours le bon pot. "
        "Comment limiter mon offre pour qu'elle reste simple ?",
    ),
    "menus": (
        "Je mets déjà à jour les prix et la mise en page du menu PDF du restaurant où je "
        "travaille, dans Canva. Je ne sais pas créer de sites web. "
        "Quelle petite prestation proposer ?",
        "Je ne peux pas montrer le menu de mon employeur et je n'ai pas de restaurateur à appeler. "
        "Comment démarrer seul avec Canva ?",
        "J'ai créé mon exemple fictif. Je peux y consacrer seulement une heure par semaine. "
        "Quel premier test commercial est raisonnable ?",
    ),
    "support_debutant": (
        "Bonjour, j'aimerais lancer un petit business, mais je ne sais pas quoi faire.",
        "Je travaille dans le support informatique. Je connais un peu les outils IA, "
        "mais je n'ai jamais créé de business.",
        "Environ 8 heures par semaine, surtout le soir et le week-end.",
        "J'aime bien tester les outils IA et aider les gens à résoudre leurs problèmes.",
        "Je ne sais pas trop, justement. Je n'ai jamais vendu de service.",
        "Je préfère les petites entreprises, mais je ne sais pas ce que je pourrais "
        "leur proposer concrètement.",
    ),
    "gestion": (
        "J'aide ma sœur à classer ses factures PDF et à relever les dates dans Excel. "
        "J'aimerais faire un peu d'argent avec ça, mais je ne sais pas à qui m'adresser.",
        "J'ai deux soirées libres. Je ne fais pas de comptabilité et je ne connais "
        "ni les macros ni les outils d'automatisation. Que pourrais-je vendre concrètement ?",
    ),
    "support_pratique": (
        "Au support informatique je dépanne surtout les problèmes d'imprimantes et "
        "j'explique aux gens comment les résoudre. Je ne sais ni programmer ni automatiser. "
        "Je veux travailler à distance le soir. Que proposer à une petite entreprise ?",
        "Je n'ai pas de clients ni de collègues disponibles pour un essai. "
        "Par quoi je commence cette semaine ?",
    ),
    "automatisation_pratiquee": (
        "Je travaille dans le support. J'ai construit et mis en service trois scénarios "
        "Make qui envoient à l'équipe des alertes à partir d'un formulaire. Je les ai "
        "testés et corrigés moi-même. Quelle petite prestation puis-je vendre à une PME ?",
        "En fait, je ne veux pas maintenir des intégrations chez les clients. "
        "Que puis-je proposer à la place ?",
    ),
    "couture": (
        "Je répare souvent les ourlets et les coutures ouvertes de mes vêtements. "
        "Je veux travailler depuis chez moi. Qu'est-ce que je peux proposer ? "
        "Je n'ai jamais posé de fermeture éclair et je ne veux pas en poser.",
        "Je ne connais pas de commerçants. Comment tester l'idée sans promettre trop ?",
    ),
    "ia": (
        "Je travaille au support informatique, je sais rédiger des réponses clients avec "
        "l'IA. Mon compte Instagram n'a rien rapporté : j'avais une audience mais aucune "
        "offre et aucun moyen de trouver des clients. J'ai 8 h par semaine, 120 €, "
        "je vise 100 € par mois et peux travailler à distance en France. Que lancer ?",
    ),
    "bougies": (
        "Je débute avec les bougies parfumées à Lyon. J'ai 6 h par semaine et 300 € maximum. "
        "Je veux vendre cinq cadeaux en deux mois. Un de mes prototypes surchauffe. "
        "Qu'est-ce que je fais maintenant ?",
    ),
    "photo": (
        "J'ai perdu 400 € dans un stock de bijoux. J'aime photographier les produits, j'ai "
        "un smartphone, 6 h par semaine et 80 € à Lille. Je vise 150 € par mois. "
        "J'ai proposé un pack de 8 photos par email à 8 artisans, zéro réponse. "
        "Dois-je abandonner ?",
        "Voici mon message : « Bonjour, je propose des services de photographie. "
        "Contactez-moi si intéressé. » Comment l'améliorer ?",
    ),
    "cours": (
        "Je donne déjà des cours de maths en visio à quatre collégiens en France à 25 €/h. "
        "Je veux deux élèves de plus, j'ai deux créneaux de cours et 3 h par semaine pour "
        "prospecter, sans site ni publicité. Un parent intéressé a un budget de 20 €. "
        "Est-ce que je dois baisser mon prix ?",
    ),
    "salon": (
        "Je veux coder une application IA de rendez-vous pour des salons à Casablanca. "
        "Un salon oublie des messages WhatsApp et confirme parfois deux fois le même "
        "créneau. J'ai déjà passé trois mois à coder sans utilisateur. J'ai 5 h par "
        "semaine et 300 DH maximum, sans abonnement. Que tester d'abord ?",
        "Il accepte un calendrier qu'il contrôle mais refuse un formulaire et tout accès "
        "à ses messages ou aux numéros de ses clients. Comment adapter le test ?",
    ),
    "cv": (
        "J'aide mes amis avec leurs CV. Sur Etsy j'avais créé beaucoup de planners mais "
        "je n'avais aucun visiteur. Je veux gagner 120 € par mois, avec 4 h par semaine "
        "et 50 € maximum. Ma cible est les étudiants en Belgique à distance. Quelle offre ?",
        "Non, pas de recherche maintenant. Pourquoi ce service plutôt que des modèles ?",
    ),
    "inedit": (
        "Je répare déjà des vélos le samedi, j'ai 5 clients qui reviennent. "
        "Je peux ajouter 2 h par semaine, j'ai 100 € et ne veux pas me déplacer. "
        "Une personne veut une réparation à domicile et propose 35 €. "
        "Devrais-je changer toute mon offre ?",
    ),
    "inedit_mobile": (
        "Je répare déjà des vélos le samedi, j'ai 5 clients qui reviennent. "
        "Je peux ajouter 2 h par semaine et j'ai 100 €. Je suis disposé à me déplacer "
        "dans le quartier si c'est rentable. Une personne veut une réparation à domicile "
        "et propose 35 €. Devrais-je changer toute mon offre ?",
    ),
}


def main() -> None:
    if os.environ.get("NEUROCOACH_LLM_PROVIDER") != "openai" or not os.environ.get(
        "NEUROCOACH_SPENDING_CAP_USD"
    ):
        raise SystemExit("Configurer le fournisseur OpenAI et le plafond avant la recette.")
    user = "evaluation-v1"
    print("# Transcriptions — recette réelle NeuroCoach\n", flush=True)
    with TemporaryDirectory() as directory:
        settings = Settings.from_env().model_copy(
            update={"data_dir": Path(directory), "research_simulation": True}
        )
        runtime = build_coach_runtime(settings)
        try:
            runtime.app.coach.ensure_user(user, "Compte fictif")
            for name, messages in CASES.items():
                if len(sys.argv) > 1 and name not in sys.argv[1:]:
                    continue
                project = runtime.agent.start_project(user)
                assert not runtime.agent.history(user, project.id), name
                print(f"\n## {name}", flush=True)
                for index, message in enumerate(messages, start=1):
                    start = monotonic()
                    turn = runtime.agent.send_message(user, project.id, message)
                    print(f"\n### Tour {index} ({monotonic() - start:.1f} s)", flush=True)
                    print(f"\n**Utilisateur** — {message}\n", flush=True)
                    print(f"**Coach**\n\n{turn.reply}\n", flush=True)
                    print(f"```text\n{turn.timings}\n```", flush=True)
                    if turn.error:
                        print(f"ERREUR : {turn.error}", flush=True)
        finally:
            runtime.checkpointer.conn.close()


if __name__ == "__main__":
    main()
