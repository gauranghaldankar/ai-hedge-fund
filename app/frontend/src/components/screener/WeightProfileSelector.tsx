import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { WeightProfileName } from './types';
import { PROFILES } from './profiles';

interface WeightProfileSelectorProps {
  value: WeightProfileName;
  onChange: (profile: WeightProfileName) => void;
}

const ALL_PROFILES: { name: WeightProfileName; label: string; description: string }[] = [
  { ...PROFILES.medium_long },
  { ...PROFILES.short_term },
  { name: 'custom', label: 'Custom', description: 'Set your own weights.' },
];

export function WeightProfileSelector({ value, onChange }: WeightProfileSelectorProps) {
  return (
    <div className="flex items-center gap-1 bg-muted/40 rounded-lg p-1">
      {ALL_PROFILES.map((p) => (
        <Button
          key={p.name}
          variant="ghost"
          size="sm"
          onClick={() => onChange(p.name)}
          title={p.description}
          className={cn(
            'h-7 px-3 text-xs rounded-md transition-all',
            value === p.name
              ? 'bg-background shadow-sm text-foreground font-medium'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {p.label}
        </Button>
      ))}
    </div>
  );
}
