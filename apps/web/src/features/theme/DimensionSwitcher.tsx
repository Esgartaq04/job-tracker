import { DIMENSIONS, DIMENSION_LABELS, usePrefs, type Dimension } from "../../lib/prefs";

const BLOCKS: Record<Dimension, string> = {
  overworld: "/textures/grass_side.png",
  nether: "/textures/netherrack.png",
  end: "/textures/end_stone.png",
};

/** Three blocks, one per dimension. Labels show on wide screens; the block alone on phones. */
export function DimensionSwitcher({ showLabels = true }: { showLabels?: boolean }) {
  const dimension = usePrefs((state) => state.dimension);
  const setDimension = usePrefs((state) => state.setDimension);

  return (
    <div role="group" aria-label="Dimension" className="flex gap-1">
      {DIMENSIONS.map((name) => {
        const active = name === dimension;
        return (
          <button
            key={name}
            type="button"
            onClick={() => setDimension(name)}
            aria-pressed={active}
            title={DIMENSION_LABELS[name]}
            className={[
              "mc-button flex items-center gap-1.5 px-1.5 py-1 text-xs",
              active ? "border-slate-100" : "opacity-75 hover:opacity-100",
            ].join(" ")}
          >
            <img src={BLOCKS[name]} alt="" width={18} height={18} className="pixelated" />
            <span className={showLabels ? "hidden lg:inline" : "sr-only"}>
              {DIMENSION_LABELS[name]}
            </span>
          </button>
        );
      })}
    </div>
  );
}
