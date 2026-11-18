# Contributing to Rudo

Thank you for helping to improve Rudo. Corrections and additions are welcome, especially from first-language speakers, clinicians and the human agents who answer escalations.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a problem.** A wrong or unsafe answer, a mistranslation, a reply in the wrong language, a missed danger sign, a bug in the human hand-off or the shop.
- **Correct existing content.** Fix a fixed message in one of the per-language maps, or a danger-sign term.
- **Add content.** A new language, danger-sign terms from a clinician who speaks the language, or health content in `training/`.
- **Improve the project.** Code, documentation, evaluation and troubleshooting notes.

You do not need to write code to contribute. If you are not comfortable with Git, open an issue describing the correction, or email developers@dawa-health.com, and a maintainer will make the change and credit you.

## Rules for all contributions

- **No personal or patient information.** Never include names, phone numbers, WhatsApp messages, exported conversations, logs or case details from real people, even if de-identified. This applies to issues, tests, examples and `training/`. Use made-up messages.
- **No secrets or phone numbers.** Never commit tokens, keys, or the WhatsApp numbers of users or human agents. Read agent numbers from an environment variable.
- **Only share what you have the right to share.** Do not copy text from books, websites, guidelines or other datasets unless their license allows it. This includes training data. Say where information came from.
- **Health content must be accurate and safe.** Base it on current national guidance for Zimbabwe or Zambia, or on WHO guidance, and say which in the pull request.
- **Local-language content must be written or checked by a first-language speaker.** This includes every fixed message: welcome, greetings, thinking, failure, agent hand-off, follow-up and shop texts. Users see these exactly when something has gone wrong. Do not submit unreviewed machine translation.
- **Keep the safety net.** Do not remove or weaken the danger-sign check, the referral line or the route to a human without an agreed issue and clinical review.

## Reporting a problem

Open an issue and include:

- the language, and a made-up message that shows the problem (never a real user's message);
- what Rudo replied, and what was wrong with it;
- what it should say, if you know;
- the pipeline log lines (question, English question, English reply, final reply) from your own test, if you have them;
- a source, for clinical corrections.

For a security vulnerability, or personal information that has been published by mistake, do not open a public issue. Email hello@dawa-health.com.

## Making a change

Nobody commits directly to `main`. All changes go through a pull request.

1. Open an issue first for anything larger than a small correction, so it can be discussed before you do the work. Adding a language, changing the guardrails, or changing the model, adapter or pivot settings always needs an issue.

2. Fork the repository and create a branch. Name it after the change:

   ```
   git checkout -b fix/shona-danger-sign-terms
   git checkout -b add/lozi-shop-messages
   git checkout -b docs/vercel-timeouts
   ```

3. Make the change. See "Working on the code" below.

4. Test it on your machine. See "Checks" below.

5. Commit with a short message that says what changed and where:

   ```
   Add Ndebele terms for heavy bleeding to danger signs
   ```

6. Open a pull request against `main`. Say what changed, why, and how you tested it, ideally with sample messages in more than one language. Link the issue it resolves.

7. Respond to review. Push further commits to the same branch. A maintainer merges the pull request once it is approved.

## Working on the code

Each of these rules was learned from a failure. Keep them unless an agreed issue says otherwise:

- Only English text reaches MedGemma for pivoted languages.
- Fixed UI text is never stored in the chat history.
- Each stored message keeps an English version in `message_en`.
- Gemini is used only to classify the language of a message. Replies never come from Gemini.
- Inference uses the same Gemma turn format as training, sends at most the last two question and answer pairs, and stays greedy.
- The guardrails in `medgemma_guardrails.py` run on every reply, even when a model or translation step has failed.
- The webhook always answers 200, and message ids are stored so a redelivery never produces a second reply.

Also:

- **Fixed user-facing text goes in the per-language maps** in `main.py`, for every supported language.
- **Database changes go in `supabase_schema.sql`.** Every new table needs Row Level Security enabled, like the existing ones.
- **Document configuration.** Add any new environment variable to the Configuration reference in the README.
- **Keep changes small.** One language or one kind of fix per pull request is easier to review.

## Checks

Before opening a pull request, test the change end to end, as described under "Testing and verification" in the README:

- run the connection checks against both model services;
- run the bot locally with `python3 main.py` and send test messages through a test WhatsApp number, in more than one language if your change affects languages;
- check in Supabase that the history looks right: `message_en` is filled for pivoted languages, and no fixed UI text is stored as bot messages;
- if you changed the guardrails, send messages that contain danger signs and check that the referral line comes first.

Say in the pull request which messages you sent and what came back.

## Adding a language

Open an issue first. The proposal should name the translators, the first-language reviewer, and a clinician who speaks the language and can supply danger-sign terms. Then follow "Adding or changing a language" in the README: the language detection, the TranslateGemma language code, every fixed message map and the danger-sign list.

Check the language code against TranslateGemma with real sentences. In the pull request, include a first-language speaker's review of a handful of translated answers, paying special attention to numbers, weeks, doses and danger signs. Add the language and its contributors to the README.

## Changing the model, adapter or pivot settings

A change to the adapter, the training format, the generation settings or `TRANSLATE_LANGS` changes every answer, so it needs an issue. Compare the old and new versions on the evaluation set and put the results in the pull request. Move a language into or out of `TRANSLATE_LANGS` only where the evaluation shows it does better.

## Review and approval

| Change | Approvals needed |
| --- | --- |
| Documentation, tests and code | One maintainer |
| Health content, guardrails and danger-sign terms | One maintainer and one clinical reviewer |
| Fixed messages or other content in a local language | One maintainer and one language reviewer for that language |
| Model, adapter or pivot settings | One maintainer, with evaluation results in the pull request |

A change that falls under more than one row needs all of those approvals. Reviewers check that the content is accurate and safe, reads naturally in its language, contains no personal information or secrets, and keeps the safety rules above. Maintainers aim to give a first response within seven days.

## Credit

Contributors are credited through their commits. When a maintainer makes a change for you from an issue or an email, they credit you as a co-author. Contributors to each language are listed in the README.

## License

The code is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). By submitting a contribution you agree that it is licensed under the same terms, and you confirm that you have the right to submit it. MedGemma and TranslateGemma are governed by Google's terms for those models. The LoRA adapter, the training data and the health content in `training/` may have their own terms, as described in the README.

## Questions

Open an issue, or email developers@dawa-health.com.
