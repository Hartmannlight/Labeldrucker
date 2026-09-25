# Template library and AI assistant

PrintHub owns saved templates and their metadata. Studio offers four library views:
active, favorites, archive, and all. Favorites are the small set used often;
archiving hides a saved template from the active library and the normal Quick
print selector without deleting it. Search covers names, descriptions, usage
context, IDs and tags; sorting covers name, last change and label area. Favorite
and archive changes update metadata only, so they do not rerender a thumbnail.
This library currently contains PrintHub's ZPL templates. Image designer
raster designs remain a separate browser-local workflow.

`description` explains what the label is for. `usage_context` records where it is
used, what data is expected and any operating constraints. This text is useful
both to people searching the library and to the optional assistant. Templates
saved before these fields existed remain readable.

## Sample values and printing

`sample_data` is for the saved thumbnail. `print_defaults` is a separate object
for the Quick print form. Save `print_defaults` as `{}` to start with blank fields
while using fictional values in `sample_data` for an informative thumbnail.
Older templates without `print_defaults` now start with empty print fields as
well. Their sample values remain available for thumbnails.
When stored thumbnail generation is enabled, saving the
template renders from `sample_data` as before. Live preview remains controlled
by its own Labelary switch. If the thumbnail service fails, the template still
saves and Studio reports that its thumbnail is unavailable. It can be retried
with **Regenerate thumbnails**.

The library shows a clear notice when stored thumbnails are disabled. With
thumbnails enabled, **Regenerate thumbnails** rebuilds the currently filtered
set of up to 50 templates from their saved sample data. This requires the
PrintHub admin token and leaves each existing image intact if its regeneration
fails.

## AI draft workflow

Set an OpenRouter key as `PRINTHUB_AI_API_KEY` on the PrintHub service. The
default model is `~openai/gpt-sol-latest`; `PRINTHUB_AI_MODEL` can select another
OpenRouter model that supports structured JSON output. The key stays server-side.
The generation endpoint requires the
PrintHub admin token. No API key is required for browsing, editing or printing
templates.

In Studio, open **AI template assistant**, describe the label, choose its size
and generate a draft. Studio shows a one-time thumbnail with fictional example
values even when live preview is off. Designer keeps this image as a clearly
marked snapshot; later edits are not shown in it while live preview is off.
The server supplies the model with the zplgrid layout
contract and validates the returned template by compiling it with fictional
sample values. It does not print or save the draft. Open it in Designer, inspect
the layout and fields, then save it through the normal Template Store dialog.
The generated sample values populate thumbnails; `print_defaults` starts empty.

The **Use selected saved templates as examples** option is off by default.
When enabled, choose up to three named templates before generating. Only those
templates' JSON layouts and metadata are sent to the configured AI service.
The sample-data files are not sent, but literal text in template layouts can
still contain sensitive content. OpenRouter routes only
to endpoints that support the requested response format and filters out providers
that collect data. Provider handling still depends on the selected model and
OpenRouter account settings.
See the [OpenRouter quickstart](https://openrouter.ai/docs/quickstart) and
[structured-output guide](https://openrouter.ai/docs/guides/features/structured-outputs)
for the API contract.

For local development, rebuild the PrintHub and Studio images after changing
their sources. Published `latest` images do not contain local edits until a
release is built and published.

## Further organization

Favorite and archive are global properties of a shared template library. This
keeps the current single-operator installation simple. If the product gains
user accounts, personal favorites should move to per-user preferences while
archive remains a shared library state. Collections or folders are worth adding
only after usage shows that tags, search and archive cannot keep the library
manageable. Usage frequency should be based on successful print jobs, never on
thumbnail views or AI references.
The library card opens the normal Quick print form; it does not send a label
immediately. That remains useful when variable values, the loaded media or the
target printer need checking before a physical print.
