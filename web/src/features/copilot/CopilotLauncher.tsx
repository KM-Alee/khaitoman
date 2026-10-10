/** "Ask AabFlow" button that opens the assistant slot. */
import { Sparkles } from "lucide-react";
import { useAppActions } from "@/app/actions";
import { Button, type ButtonSize, type ButtonVariant } from "@/components/ui/Button";

export function CopilotLauncher({
  label = "Ask AabFlow",
  variant = "secondary",
  size = "sm",
  className,
}: {
  label?: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
}) {
  const actions = useAppActions();
  return (
    <Button variant={variant} size={size} className={className} onClick={actions.openAssistant} data-testid="copilot-launcher">
      <Sparkles size={14} aria-hidden /> {label}
    </Button>
  );
}
