# Séance compared with ten COBOL modernization products

Read in November 2026 from each vendor's public documentation where it could be found, and from a third-party comparison
for the few products whose own pages were not read. This is a feature comparison of what is written down, not a benchmark.

**How to read the table.** `✓` means the capability is described in a vendor source I read. `·` means I did not find it in
what I read. It does not mean the product lacks it. Séance's column is what the code in this repository does today.

## What each product is

| Product | What it is | Source |
| --- | --- | --- |
| **Séance** | Local verification tool: runs the original COBOL, translates to Python by fixed rules, proves the Python matches | this repository |
| **AWS Transform for mainframe** | Managed agentic service: analysis, documentation, business rules, decomposition, refactor to Java, "reimagine" to any stack, test planning | [AWS docs](https://docs.aws.amazon.com/transform/latest/userguide/transform-app-mainframe.html) |
| **IBM ADDI and Bob for Z** (ex watsonx Code Assistant for Z) | ADDI: application discovery, flow and data-flow analysis. Bob for Z: IDE assistant, COBOL to Java, generated unit tests | [ADDI](https://www.ibm.com/docs/en/addi/6.1.4?topic=guide-product-overview) |
| **Google Mainframe Assessment Tool and Dual Run** | MAT: assessment and business-rule extraction. Dual Run: replay production and compare outputs | [MAT](https://docs.cloud.google.com/mainframe-assessment-tool/docs/overview) |
| **Mechanical Orchard Imogen** | Behaviour-first platform: captures real data flows, writes characterization tests, proves equivalence | [Platform](https://www.mechanical-orchard.com/platform) |
| **Rocket Enterprise Analyzer** (ex Micro Focus) | Application intelligence: analysis, dependency mapping, documentation, business rule mining | [Product page](https://www.rocketsoftware.com/products/enterprise-suite/enterprise-analyzer) |
| **Heirloom Computing** | COBOL to Java compiler and runtime (CICS, JCL, VSAM, IMS) | [Support site](https://heirloomcomputing.zendesk.com/) |
| **TSRI JANUS Studio** | Multi-language to Java or C# conversion with traceability | third-party comparison only |
| **Astadia** | COBOL to Java or C# with a test factory | third-party comparison only |
| **CAST Imaging** | Application analysis and mapping | third-party comparison only |
| **Raincode** | COBOL compiler for .NET with a Visual Studio plugin | [Product page](https://www.raincode.com/cobol/) |

## Capabilities

| Capability | Séance | AWS | IBM | Google | Mech. Orchard | Rocket | Heirloom | Raincode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Program and dependency graphs | ✓ | ✓ | ✓ | ✓ | · | ✓ | · | · |
| Paragraph flow: PERFORM, GO TO, fall-through | ✓ | · | ✓ | · | · | · | · | · |
| Dead code | ✓ | · | · | · | · | · | ✓ | · |
| Size and complexity assessment of a whole estate | ✓ | ✓ | ✓ | ✓ | · | ✓ | · | · |
| Migration order (waves) | ✓ | ✓ | · | · | · | · | · | · |
| Data lineage | ✓ | ✓ | ✓ | · | ✓ | · | · | · |
| Data dictionary | ✓ | ✓ | · | · | · | · | · | · |
| Cross-reference: where a field is defined, changed and used, across programs | ✓ | · | ✓ | · | · | ✓ | · | · |
| Data file viewer: records split by the copybook, CSV export | ✓ | · | · | · | · | ✓ | · | · |
| Business rules extracted | ✓ | ✓ (Gherkin) | ✓ | ✓ | ✓ | ✓ | · | · |
| Generated documentation | ✓ | ✓ | · | ✓ | · | ✓ | · | · |
| Runs the original program for the expected answer | ✓ (GnuCOBOL, local) | · | · | ✓ (Dual Run, on the mainframe) | ✓ | · | · | · |
| Byte-level output comparison | ✓ | · | · | ✓ | ✓ | · | · | · |
| Parallel run against your own mainframe output | ✓ | ✓ | · | ✓ | ✓ | · | · | · |
| Failure shrunk to the smallest input | ✓ | · | · | · | · | · | · | · |
| Generated tests | ✓ (pytest suite in the package) | ✓ | ✓ | · | ✓ | · | · | · |
| Mutation testing, evidence coverage, hash receipt | ✓ | · | · | · | · | · | · | · |
| CICS and embedded SQL programs | ✓ (replayed on SQLite) | ✓ | ✓ | · | · | · | ✓ | · |
| JCL jobs | ✓ (every step run on both sides) | ✓ | ✓ | · | ✓ | · | ✓ | · |
| Natural-language explanation, chat | partly: every statement described in plain English; chat through Kiro over MCP | ✓ | ✓ | ✓ | · | ✓ | · | · |
| Generates Java or C# | · | ✓ | ✓ | partners | ✓ | · | ✓ | .NET |
| Check history and CI output (JUnit) | ✓ | · | · | · | · | · | · | · |
| Works offline, no account | ✓ | · | · | · | · | · | · | · |

TSRI, Astadia and CAST are left out of the table because I found no vendor page that states these capabilities; the
third-party comparison describes them as converters and analyzers.

## What Séance does not do, on purpose

- **No language model.** Translation, rules and descriptions come from fixed rules, so the same COBOL always gives the same
  answer and nothing is made up. The cost is that it cannot explain code in free text or answer questions. The MCP server
  lets an agent such as Kiro read the same analysis and do that part.
- **Python only.** It does not generate Java or C#.
- **It is not a runtime.** The package it exports runs the program, but Séance is not a hosting platform for CICS regions,
  JCL schedulers or databases.
- **GnuCOBOL is the stand-in for your compiler.** A parallel run against your mainframe's output exists so you can see
  where the two differ.
- **No IMS, REPORT or SCREEN sections yet**, and no POINTER arithmetic. Data declared GLOBAL in one program of a file is not
  shared with the other programs of that file.

## What was added after reading these products

Static analysis (flow graph, dead code, complexity, cross-reference), a data dictionary and lineage, business rules with
Gherkin export, an assessment of the whole workspace with migration waves and CSV, parallel runs against mainframe output,
a pytest suite in every exported package, an HTML report, a history of every check, and `check-all` with JUnit output for
build pipelines.

Release 1.1.0 added a workspace cross-reference (where a field is defined, changed and used, from the command bar, as in
IBM ADDI and Rocket Enterprise Analyzer), a record viewer that splits any saved data file by its copybook with CSV export
(as in Rocket's data file tools), and translator support for what those products' compilers accept and Séance did not:
compiler directives, REPLACE, named constants, DECIMAL-POINT IS COMMA, several programs in one file, DELETE FILE and
LENGTH OF.

## Sources

- AWS: [Modernization of mainframe applications](https://docs.aws.amazon.com/transform/latest/userguide/transform-app-mainframe.html),
  [Reimagine and automated testing](https://aws.amazon.com/blogs/aws/aws-transform-for-mainframe-introduces-reimagine-capabilities-and-automated-testing-functionality/),
  [rules in Gherkin](https://repost.aws/articles/ARi6q31Py5RbWHQX_I42ayzg/%F0%9F%8C%9F-mainframe-to-aws-building-agentic-ai-workflow-to-modernize-legacy-applications)
- IBM: [ADDI product overview](https://www.ibm.com/docs/en/addi/6.1.4?topic=guide-product-overview), [ADDI program flow](https://www.ibm.com/docs/en/addi/6.1.3?topic=layouts-program-flow)
- Google: [MAT overview](https://docs.cloud.google.com/mainframe-assessment-tool/docs/overview), [review results](https://docs.cloud.google.com/mainframe-assessment-tool/docs/review-results), [business rules](https://docs.cloud.google.com/mainframe-assessment-tool/docs/business-rules-extraction), [Dual Run](https://docs.cloud.google.com/mainframe-dual-run)
- Mechanical Orchard: [Platform](https://www.mechanical-orchard.com/platform), [Verification problem](https://www.mechanical-orchard.com/research/mainframe-modernization-is-a-verification-problem), [Summer 2026 release](https://www.mechanical-orchard.com/insights/whats-new-in-imogen-the-summer-2026-release)
- Rocket: [Enterprise Analyzer](https://www.rocketsoftware.com/products/enterprise-suite/enterprise-analyzer), [Business Rule Manager](https://www.rocketsoftware.com/sites/default/files/resource_files/business-rule-manager.pdf)
- Heirloom: [dead code analysis option](https://heirloomcomputing.zendesk.com/hc/en-us/articles/8787997420564-Building-a-facade-around-existing-COBOL-logic-to-create-a-service), [Java generation](http://heirloomcomputing.zendesk.com/hc/en-us/articles/212580926-Java-Generation-Options)
- Raincode: [COBOL compiler](https://www.raincode.com/cobol/)
- Third-party comparison used for IBM Bob, TSRI, Astadia and CAST: [vusatui/rnd-research](https://github.com/vusatui/rnd-research/blob/main/legacy-modernization/comparison.md)
