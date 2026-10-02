/** Equipment families the knowledge base covers (also offered when a technician corrects a ticket). */
export const EQUIPMENT_TYPES = ['pump', 'motor', 'printer', 'HVAC', 'conveyor belt', 'generator'] as const

export type EquipmentType = (typeof EQUIPMENT_TYPES)[number]
