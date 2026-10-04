import { usePrefs } from "../../lib/prefs";

/** Notches stop helping past this many segments; the bar just fills smoothly. */
const MAX_NOTCHES = 30;

/**
 * The weekly goal as a Minecraft XP bar: the green number is this week's count and
 * each notch is one application towards the goal.
 */
export function XpBar({ thisWeek }: { thisWeek: number }) {
  const goal = usePrefs((state) => state.weeklyGoal);
  const setGoal = usePrefs((state) => state.setWeeklyGoal);
  const progress = Math.min(1, thisWeek / goal);
  const reached = thisWeek >= goal;

  return (
    <div>
      <p className="text-center font-[family-name:'Silkscreen',var(--font-pixel)] text-3xl leading-none text-xp-ink [text-shadow:2px_0_0_#000,-2px_0_0_#000,0_2px_0_#000,0_-2px_0_#000]">
        {thisWeek}
      </p>
      <div
        role="progressbar"
        aria-label="Applications this week"
        aria-valuemin={0}
        aria-valuemax={goal}
        aria-valuenow={Math.min(thisWeek, goal)}
        aria-valuetext={`${thisWeek} of ${goal}`}
        className="relative mt-2 h-3 border-2 border-black bg-xp-track"
      >
        <div className="h-full bg-xp" style={{ width: `${progress * 100}%` }} />
        {goal <= MAX_NOTCHES && (
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              backgroundImage: `repeating-linear-gradient(to right, transparent 0, transparent calc(${100 / goal}% - 2px), rgb(0 0 0 / 0.55) calc(${100 / goal}% - 2px), rgb(0 0 0 / 0.55) ${100 / goal}%)`,
            }}
          />
        )}
      </div>
      <p className="mt-2 text-center text-sm text-slate-300">
        {reached ? (
          <span className="text-xp-ink">Level up! Weekly goal reached.</span>
        ) : (
          <>
            {thisWeek} / {goal} this week · {goal - thisWeek} to go
          </>
        )}
      </p>

      <div className="mt-3 flex items-center justify-center gap-2 text-xs text-slate-400">
        <span>Goal</span>
        <button
          type="button"
          onClick={() => setGoal(goal - 1)}
          disabled={goal <= 1}
          aria-label="Lower weekly goal"
          className="mc-button h-6 w-6 leading-none disabled:opacity-40"
        >
          −
        </button>
        <span className="w-6 text-center tabular-nums text-slate-200">{goal}</span>
        <button
          type="button"
          onClick={() => setGoal(goal + 1)}
          disabled={goal >= 99}
          aria-label="Raise weekly goal"
          className="mc-button h-6 w-6 leading-none disabled:opacity-40"
        >
          +
        </button>
        <span>per week</span>
      </div>
    </div>
  );
}
