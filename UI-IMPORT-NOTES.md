# UI Polish v4 review import

Source: Otherwise-UI-Flagship-Polish-v4.zip (SHA256 65cfcaa4467df5500bfe02c42b8a968fed6f25fe7acaaf543a25dbef8738bdd3).

Branch uiv4 overlays the supplied archive onto main at 963b8be025df95ed3d41db917966f59175574ade. Files absent from the archive are retained. The ui branch retains the previous Hero V3 import.

Claude: select the intended UI changes from web/ and associated UI tests. The archive is a repository snapshot and may contain older backend, dependency, deployment, and documentation files. Preserve current main versions of those files; do not merge this branch wholesale. Check compatibility with current air pages and feature flags, and review desktop and mobile before merging selected changes.

Archive extraction was verified byte-for-byte before adding this note. No application tests or browser validation were run for this review import. This task did not modify main.
