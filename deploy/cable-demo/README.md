# Prepared cable-flag demo

This isolated Docker project uses the current Studio and PrintHub source, a
virtual Zebra over TCP, and its rendered output. All endpoint values are fictional.
The media is 75 × 50 mm, with a 6 mm cable diameter and 2 mm text padding.

Open these local URLs after preparation:

- [Prefilled Studio print form](http://localhost:8188/?template_id=kabel-demo-75x50#/print)
- [Virtual printer](http://localhost:8191/)
- [PrintHub jobs](http://localhost:8188/#/jobs)

From the repository root, build and start with:

```powershell
docker compose --env-file deploy/cable-demo/demo.env -f deploy/cable-demo/compose.yaml build
docker compose --env-file deploy/cable-demo/demo.env -f deploy/cable-demo/compose.yaml up -d --no-build --wait
docker compose --env-file deploy/cable-demo/demo.env -f deploy/cable-demo/compose.yaml exec -T printhub python /demo/prepare.py
docker compose --env-file deploy/cable-demo/demo.env -f deploy/cable-demo/compose.yaml exec -T printhub python /demo/verify_burst.py
```

Preparation loads media, updates the stored template, checks both label layouts,
generates a thumbnail, sends one native ZPL job containing two labels through
PrintHub and ZebraTamer, and waits for both virtual printer PNGs. It writes the
result and images to `output/`. The demo uses the project's normal Studio UI.
Once a prepared result exists, the script verifies it without sending duplicates.

The burst check submits five jobs concurrently, each containing two labels. It
requires all ten images to render and all five jobs to reach transport acceptance.
The same check runs in the platform integration pipeline. The emulator processes
complete labels on open TCP connections and queues image rendering to avoid
[Labelary rate limits](https://labelary.com/service.html#limits).

The running demo uses project name `cable-demo` and its own named volumes.
HTTP ports bind only to localhost. Labelary renders the fictional demo content.
PrintHub records `transport_accepted`; the emulator independently confirms that
both labels were received and rendered. This is a virtual print, not a hardware
confirmation.

The emulator's recent-job list is in memory. Saved label images remain on disk,
but restarting the emulator clears that list. If that happens,
the prepare script deliberately stops instead of silently duplicating old jobs.
