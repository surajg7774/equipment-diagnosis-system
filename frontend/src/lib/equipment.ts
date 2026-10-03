/**
 * Equipment kinds offered as SUGGESTIONS when typing an equipment type (diagnosis form and the
 * technician's correction form). Any text is accepted: the system diagnoses any physical device, not
 * just the families its knowledge base was seeded with (the first six).
 */
export const EQUIPMENT_TYPES = [
  'pump',
  'motor',
  'printer',
  'HVAC',
  'conveyor belt',
  'generator',
  'laptop',
  'mobile phone',
  'refrigerator',
  'washing machine',
  'car',
] as const

export type EquipmentType = (typeof EQUIPMENT_TYPES)[number]
