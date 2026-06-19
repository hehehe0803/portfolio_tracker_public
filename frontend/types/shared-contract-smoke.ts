import type {
  AlertEventContract,
  AlertRuleContract,
  AssetSnapshot,
  ImportArtifactContract,
  NoteContract,
  TagContract,
  TransactionRecord,
  IngestionEvent,
} from "../../shared/typescript/contracts"

export type SharedContractSmoke = {
  asset: AssetSnapshot
  transaction: TransactionRecord
  importArtifact: ImportArtifactContract
  alertRule: AlertRuleContract
  alertEvent: AlertEventContract
  tag: TagContract
  note: NoteContract
  ingestionEvent: IngestionEvent
}
