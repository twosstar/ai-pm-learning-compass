# Public curriculum: sources and editorial boundaries

The curriculum contains 60 independently arranged lessons, 10 modules and 120 stable knowledge points. Explanations are independently phrased teaching notes, not copied textbook text. Business examples, AI PM transfer guidance and exercise scenarios are original editorial applications. Source links allow readers to check the underlying mechanisms; they do not imply endorsement.

## Learning structure

Each module has six lessons. The progression covers product problems; machine learning and evaluation; data and experiments; language models; prompting and adaptation; RAG; agents and tools; multimodal applications; deployment and operations; and trust, governance and launch decisions. The original three public lessons and six knowledge-point IDs are retained. New material is not a reproduction of a purchased course's ordering or its question bank.

## Textbooks and openly readable chapters

46 lessons include at least one openly readable textbook chapter or online-book section. This does not mean all knowledge in those lessons comes from books or that every book was read cover to cover.

- [Dive into Deep Learning](https://d2l.ai/), version 1.0.3: machine learning, neural networks, attention, Transformer, vision and recommendation mechanisms.
- [Speech and Language Processing, third-edition draft](https://web.stanford.edu/~jurafsky/slp3/), August 19, 2026 draft: language models, embeddings, Transformer, RAG, adaptation, evaluation and speech. The edition is an evolving draft, not a final published third edition. Unwritten sections are not used as evidence.
- [Introduction to Information Retrieval](https://nlp.stanford.edu/IR-book/html/htmledition/irbook.html), Cambridge University Press, 2008: indexing, ranked retrieval, evaluation and text classification.
- [OpenStax Principles of Marketing](https://openstax.org/details/books/principles-marketing) and [Entrepreneurship](https://openstax.org/details/books/entrepreneurship): needs, segmentation, research, opportunity and business-model foundations. AI-specific applications are original transfer examples, not assertions that these books teach AI systems.
- [Machine Learning Systems Design](https://huyenchip.com/machine-learning-systems-design/toc.html), Chip Huyen's openly readable online primer: data, evaluation, deployment and system tradeoffs. This is **not** the commercially published book *Designing Machine Learning Systems*.

## Other evidence and outline inspiration

The remaining 14 lessons use explicitly labeled official engineering documentation, public guides, papers or author summaries. Examples include Google PAIR, Microsoft architecture documentation, Anthropic agents guidance, MCP, Hugging Face, scikit-learn, NIST and OWASP. Author summaries of *AI Engineering* are marked as author summaries, not as access to the paid book's full chapters.

Public tables of contents can inform topic coverage but are listed separately under `outline_sources`. For example, an ISL table of contents is not treated as proof that the textbook PDF was read or as a factual source for lesson explanations. The public sequence is independently assembled; mixing multiple outlines does not by itself establish permission to reproduce copyrighted expression.

## Verification and maintenance

`app/data/public_curriculum.json` records source author, title, section, edition/version, URL and type. Each lesson and knowledge point references applicable sources. Detailed source panels are omitted from the lesson reader; provenance remains in the JSON and catalog API for maintenance. Original-example labels remain visible. Questions use curated original scenarios and do not select from the local imported interview bank.

`scripts/check_curriculum.py` verifies metadata, minimum teaching completeness, module membership and ID uniqueness. Automated tests also exercise startup of all 60 lessons and preserve prior learning state during repeated synchronization. Neither check certifies all factual claims or legal clearance. References and technical guidance may change; inspect linked primary sources when revising content. Do not bundle paid text, slides, videos, scans or question-bank answers.
