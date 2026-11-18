# Rudo Project Charter

This charter describes what the Rudo project is for, what it covers, who is responsible for it and how decisions are made. It applies to everything in this repository.

## 1. Mission

Rudo exists to give women in Zimbabwe and Zambia clear, supportive maternal and women's health guidance on WhatsApp, in the language they speak. Danger signs are escalated, and a person can always take over.

## 2. Goals

- Answer in English, Shona, Ndebele, Chinyanja, Bemba, Tonga and Lozi, including mixed English and local language.
- Escalate danger signs every time, even when a model or translation service is down.
- Always keep a route to a human.
- Keep answers short, accurate and safe, using a small fine-tuned model that is affordable to run.
- Be open with users about what is stored, and protect it.
- Keep the code open and documented so others can run and improve it.

## 3. Scope

**In scope**

- The WhatsApp bot: the webhook, router, answer pipeline, human hand-off and shop (`main.py` and its modules).
- The guardrails and danger-sign list (`medgemma_guardrails.py`).
- The clients for the model services, and the reference code for running them.
- Health content and training data modules in `training/`.
- The database schema (`supabase_schema.sql`).
- Documentation, evaluation and troubleshooting notes.
- New languages, more danger-sign terms and corrections to existing content.

**Out of scope**

- Personal, patient or user data of any kind, including de-identified conversations.
- Model weights. The LoRA adapter is published separately on Hugging Face, and MedGemma and TranslateGemma are Google's models under Google's terms.
- Diagnosis, prescribing or replacing a clinician. Rudo gives general health information.
- Content that Dawa Health or the contributor does not have the right to share.

## 4. Principles

- **Safety first.** The guardrails run on every reply, danger signs put the referral line first, and the referral line stays on. Health content and danger-sign terms are reviewed by a qualified health professional before they are merged.
- **A person is always reachable.** If the services fail, Rudo says so and offers a human instead of guessing.
- **Language authority.** Content in a language is written or reviewed by a first-language speaker. Code-switching with English is kept where speakers use it. A language that translates badly is taken out of the pivot rather than shipped as it is.
- **Evidence before change.** Changes to the model, adapter or pivot are compared on an evaluation set before they are adopted.
- **Privacy.** Nothing that could identify a person is accepted into the repository. Users are told what is stored, and chat history is kept only as long as it is needed.
- **Openness.** The code and its history are public. Anyone who runs a modified version offers its source to users, as the AGPL requires.

## 5. Roles and responsibilities

| Role | Responsibilities |
| --- | --- |
| Project steward (Dawa Health) | Owns the repository, holds the copyright, sets direction and appoints maintainers. |
| Maintainers | Review and merge pull requests, cut releases, keep documentation current, and enforce this charter and the Code of Conduct. |
| Clinical reviewers | Check health content, guardrails and danger-sign terms for accuracy and safety. At least one must approve any change to them. |
| Language reviewers | Check content in their first language for correctness and natural wording. At least one must approve any change to that language's content. |
| Contributors | Anyone who opens an issue or pull request. Contributors follow the contributing guide and the Code of Conduct. |

Current maintainers and reviewers:

| Name | Role | Area |
| --- | --- | --- |
| Tariro F Munzwa | Maintainer | Repository and releases |
| Tafadzwa K Munzwa, MD | Clinical reviewer | Health content, guardrails and danger signs |
| Kudzai Mwedzi| Language reviewer | Shona, Ndebele, Chinyanja, Bemba, Tonga and Lozi content |

The contributors to each language are listed in the README.

## 6. Decision making

- Day-to-day changes are decided by pull request review. A change is merged when it has the approvals in section 7 and has been tested as the contributing guide describes.
- Maintainers aim for consensus. If maintainers cannot agree, the project steward decides.
- Larger changes need an issue for discussion first, open for at least seven days. These include adding a language, removing or weakening a guardrail, changing the model, adapter, training format or pivot settings, and changing the license.
- An urgent fix for a safety, security or privacy problem can be merged without the seven-day wait. It is discussed in an issue afterwards.
- Clinical disagreements are settled by the clinical reviewers, with reference to current national guidance in Zimbabwe and Zambia and to WHO guidance. Where guidance differs between the two countries, the content says which it follows.

## 7. How changes are made

1. Open an issue describing the problem or proposal, unless the change is a small correction.
2. Create a branch and make the change. Nobody commits directly to `main`.
3. Open a pull request that says what changed, why, and how it was tested, ideally with sample messages in more than one language.
4. Test the change end to end, as described in the contributing guide.
5. Review and approval:
   - any change: one maintainer;
   - health content, guardrails and danger-sign terms: one maintainer and one clinical reviewer;
   - content in a local language: one maintainer and one language reviewer for that language;
   - model, adapter or pivot settings: one maintainer, with evaluation results in the pull request.
6. A maintainer merges the pull request.

Details are in [CONTRIBUTING.md](CONTRIBUTING.md).

## 8. Quality

- Every change is tested end to end before it is merged. Changes to the guardrails are tested with messages that contain danger signs.
- No language is enabled in production until a first-language speaker has reviewed translated answers, with special attention to numbers, weeks, doses and danger signs.
- A sample of real conversations is reviewed regularly with clinicians, inside the live service and under its data protection rules. Corrections are fed back into the training data and guardrails. The conversations themselves never enter this repository.
- Known issues, such as the danger-sign list still being a starter list, are listed in the README until they are fixed.
- Corrections from first-language speakers and clinicians are treated as a priority.

## 9. Releases

- Releases use version numbers of the form MAJOR.MINOR.PATCH.
  - MAJOR: a change that existing deployments must act on, such as a database schema change, new required configuration or a change to the model service API.
  - MINOR: new languages, features or content.
  - PATCH: fixes, corrections and documentation.
- Each release has a tag and an entry in `CHANGELOG.md`.
- A retrained adapter is published as a new version, and the README states which version the bot uses.
- Evaluation results always state the adapter version and the `TRANSLATE_LANGS` setting they were run with.

## 10. License and contributions

The code is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). Copyright is held by Dawa Health. Contributions are accepted under the same license, and contributors confirm they have the right to share what they submit. MedGemma and TranslateGemma are governed by Google's terms. The LoRA adapter, the training data and the health content in `training/` may have their own terms, as stated in the README.

## 11. Code of Conduct

Everyone taking part in the project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Reports go to developers@dawa-health.com. Security issues go to hello@dawa-health.com.

## 12. Funding and independence

Where the project receives outside funding, funders do not decide what is merged; that is decided through the process in this charter.

## 13. Changes to this charter

Changes to this charter or to the Code of Conduct are proposed by pull request, discussed in an issue for at least seven days, and approved by the project steward.

## Contact

developers@dawa-health.com, or hello@dawa-health.com for security issues.
