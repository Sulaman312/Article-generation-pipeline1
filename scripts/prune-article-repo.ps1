# Remove social-only modules from the article repo.
$root = Split-Path -Parent $PSScriptRoot
$remove = @(
  "backend\social_pipeline.py",
  "backend\social_steps.py",
  "backend\social_input.py",
  "backend\social_prompts.py",
  "backend\social_channels.py",
  "backend\social_image_generation.py",
  "backend\social_image_styles.py",
  "backend\image_artifacts.py",
  "backend\image_overlay.py",
  "backend\image_templates.py",
  "backend\integrations\figma_templates.py",
  "backend\integrations\openai_chat.py",
  "backend\integrations\openai_images.py",
  "backend\fonts",
  "backend\api\routes\images.py",
  "scripts\import_figma_template.py",
  "atlas-ui\src\components\workspace\SocialPipelineBoard.jsx",
  "atlas-ui\src\components\workspace\ManualSocialForm.jsx",
  "atlas-ui\src\components\run\SocialStepMatrixScreen.jsx",
  "atlas-ui\src\components\run\SocialStepMatrix.jsx",
  "atlas-ui\src\components\run\SocialRunInputPanel.jsx",
  "atlas-ui\src\components\run\SocialRunInputPanel.css",
  "atlas-ui\src\components\run\ImageComposer.jsx",
  "atlas-ui\src\components\run\ImageComposer.css",
  "atlas-ui\src\components\run\ImageGenerationStep.css",
  "atlas-ui\src\components\run\ContentAngleStructured.jsx",
  "atlas-ui\src\constants\socialPipeline.js",
  "atlas-ui\src\constants\overlayFonts.js",
  "atlas-ui\src\utils\socialRunTopic.js",
  "atlas-ui\src\utils\parseContentAngleIntent.js"
)
foreach ($rel in $remove) {
  $path = Join-Path $root $rel
  if (Test-Path $path) {
    Remove-Item -Recurse -Force $path
    Write-Host "Removed $rel"
  }
}
