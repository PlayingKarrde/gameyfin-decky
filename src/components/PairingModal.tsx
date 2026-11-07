import { PhoneModal } from "../common/PhoneModal";
import { PublicSettings, getPairingStatus, startPairing, stopPairing } from "../backend";

type Props = { onPaired?: (s: PublicSettings) => void; closeModal?: () => void };

const api = { start: startPairing, status: getPairingStatus, stop: stopPairing };

/** Phone page for the Gameyfin token and, optionally, a SteamGridDB key (see pairing.py). */
export function PairingModal({ onPaired, closeModal }: Props) {
  return (
    <PhoneModal
      api={api}
      title="Gameyfin"
      description="Paste a Gameyfin personal access token on that page, and optionally a SteamGridDB API key for extra artwork."
      onDone={onPaired}
      closeModal={closeModal}
    />
  );
}
