<!--
This page is built almost entirely from ../README.md via mkdocs-include-markdown-plugin,
so there is exactly one copy of every fact -- see CONTRIBUTING.md / README.md for the
source. Two small deviations, both required because a relative link that works from the
repo root breaks once the same text is spliced into a page under docs/:

  * The CI/License/Status badge row (README lines 5-7) is dropped. The License badge
    links to the repo-root `LICENSE` file, which sits outside `docs_dir` and so can never
    resolve as an in-site relative link -- see the hand-written License section at the
    bottom of this page instead.
  * The "## Configuration reference" section is skipped here and linked to
    configuration.md instead, so the settings table exists in exactly one place in the
    built site. Its in-page anchor link from the Quickstart section is retargeted to
    that page below for the same reason.

Every `docs/PRIVACY.md` link inside the included text is rewritten automatically
(rewrite-relative-urls) to `PRIVACY.md`, which resolves correctly from this page.
-->

{% include-markdown "../README.md" end="[![CI]" %}
{% include-markdown "../README.md" start="(#installation)" end="[Configuration reference](#configuration-reference)." %}
[Configuration reference](configuration.md).
{% include-markdown "../README.md" start="[Configuration reference](#configuration-reference)." end="## Configuration reference" %}

The full settings table lives on the [Configuration](configuration.md) page.

{% include-markdown "../README.md" start="`LOGSCRIBE_PROMETHEUS_PORT` | `9095` | Port for `start_prometheus_server_if_enabled()`. |" end="## License" %}

## License

MIT License. See [LICENSE](https://github.com/nadeem4/logscribe/blob/main/LICENSE) for the full text.
