# Knowledge-base source review (audit file, not shipped in the app)

Every record in `data/knowledge_base.json` is `documented`: the cited page states the problem, its cause and a remedy,
and the record paraphrases it. This file lets you spot-check: open the source URL and find the quoted line.

- The quote is under 15 words and is copied from the page text as fetched (the check ignores case, curly quotes and dash types).
- Source kind tells you how strong the source is. `VENDOR / third-party blog` rows were used only where no primary source was found.
- Where the record has a safety note or a call-a-technician step, it is there because the source says it.

| Record | Category | Source kind | Source URL | Supporting line from the page |
|---|---|---|---|---|
| KB-004 | pump | industry body | https://www.pumps.org/2021/09/23/why-pump-pressure-lower-than-expected/ | "Low pressure at the pump inlet can cause cavitation" |
| KB-029 | pump | industry body | https://www.pumps.org/2021/09/23/why-pump-pressure-lower-than-expected/ | "otherwise the pump will not develop pressure" |
| KB-030 | pump | industry body | https://www.pumps.org/2021/09/23/why-pump-pressure-lower-than-expected/ | "Swapping the two electrical leads should get the pump rotating" |
| KB-031 | pump | industry body | https://www.pumps.org/2021/09/23/why-pump-pressure-lower-than-expected/ | "poorly tightened bolts or a cut gasket could let air into the system" |
| KB-032 | pump | industry body | https://www.pumps.org/2021/12/14/why-pump-power-is-higher-than-expected/ | "Internal wear could be resulting in volumetric losses and reduced efficiency" |
| KB-033 | pump | industry body | https://www.pumps.org/2021/09/23/why-pump-pressure-lower-than-expected/ | "incorrectly set clearances and missing or improperly installed wear rings" |
| KB-034 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "the motor size may be increased, or the load on the motor decreased" |
| KB-035 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "If the voltage is not balanced, one winding will overheat" |
| KB-036 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "an electronic phase-loss monitor is used to detect phase loss" |
| KB-037 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "Vents can be added at the top and bottom of the enclosed area" |
| KB-038 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "tight enough not to slip, but not so tight as to overload" |
| KB-039 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "Misalignment is usually corrected by placing shims under the feet" |
| KB-040 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "should contain a heating element to keep the motor dry" |
| KB-041 | motor | VENDOR / third-party blog | https://electricalacademia.com/motor-control/electric-motor-failure-causes/ | "Most motors are not designed to start more than ten times per hour" |
| KB-042 | motor | manufacturer | https://www.emerson.com/documents/automation/brochure-electric-motor-problems-diagnostic-techniques-ams-en-6652274.pdf | "Too much or too little grease is a very common problem" |
| KB-043 | motor | manufacturer | https://www.emerson.com/documents/automation/brochure-electric-motor-problems-diagnostic-techniques-ams-en-6652274.pdf | "background vibration while the motor is not running" |
| KB-044 | motor | manufacturer | https://www.emerson.com/documents/automation/brochure-electric-motor-problems-diagnostic-techniques-ams-en-6652274.pdf | "cut the life of the insulation in half" |
| KB-045 | printer | manufacturer | https://support.lexmark.com/en_us/printers/printer/C792/article/SO6330.html | "paper/media wraps around the fuser roll" |
| KB-046 | printer | manufacturer | https://www.support.xerox.com/en-us/article/KB0116619 | "Wait at least 40 minutes for the Fuser to cool down" |
| KB-047 | printer | manufacturer | https://www.support.xerox.com/en-us/article/en/1336610 | "contamination, dirt or debris within the paper path" |
| KB-048 | printer | manufacturer | https://support.brother.com/g/b/faqend.aspx?c=us&lang=en&prod=mfc885cw_all&faqid=faq00000495_027 | "paper scraps have become stuck in the print head path" |
| KB-049 | printer | manufacturer | https://support.brother.com/g/b/faqend.aspx?c=us&lang=en&prod=hl3040cn_all&faqid=faq00002573_001 | "The use of non recommended paper may cause the print quality issue" |
| KB-050 | printer | manufacturer | https://support.lexmark.com/en_us/printers/printer/C925/article/TE533.html | "replace it one at a time until the problem desists" |
| KB-051 | printer | manufacturer | https://support.brother.com/g/b/faqend.aspx?c=us&lang=en&prod=hl3040cn_all&faqid=faq00002573_001 | "identify the color of the LED head causing vertical streaks" |
| KB-016 | HVAC | manufacturer | https://www.carrier.com/us/en/residential/hvac-resources/air-conditioners/why-is-my-ac-blowing-hot-air/ | "A professional Carrier technician must locate the leak, repair it, and recharge the system" |
| KB-018 | HVAC | manufacturer | https://www.lennox.com/residential/lennox-life/consumer/why-is-your-air-conditioner-leaking-water | "The tube running from your drain pan could be disconnected or clogged" |
| KB-052 | HVAC | manufacturer | https://www.carrier.com/us/en/residential/hvac-resources/air-conditioners/why-is-my-ac-blowing-hot-air/ | "Replacing batteries or recalibrating the device often solves this" |
| KB-053 | HVAC | manufacturer | https://www.lennox.com/residential/lennox-life/consumer/outside-ac-unit-not-turning-on | "If the breaker immediately re-trips, you’ve got an overloaded circuit" |
| KB-054 | HVAC | manufacturer | https://www.lennox.com/residential/lennox-life/consumer/outside-ac-unit-not-turning-on | "A bad capacitor won’t be able to power the fan" |
| KB-055 | HVAC | manufacturer | https://www.lennox.com/residential/lennox-life/consumer/outside-ac-unit-not-turning-on | "turn off the system and allow the coils to thaw completely" |
| KB-056 | HVAC | manufacturer | https://www.lennox.com/residential/lennox-life/consumer/outside-ac-unit-not-turning-on | "usually because of a clogged condensate drain line" |
| KB-057 | HVAC | manufacturer | https://www.carrier.com/us/en/residential/hvac-resources/air-conditioners/why-is-my-ac-blowing-hot-air/ | "Dirty air filters are a primary culprit" |
| KB-058 | HVAC | manufacturer | https://www.lennox.com/residential/lennox-life/consumer/outside-ac-unit-not-turning-on | "a malfunctioning fan motor due to worn bearings or wear and tear over time" |
| KB-059 | conveyor belt | manufacturer | https://www.flexco.com/EN/Blogs/HDBCP-HDMBF/Top-10-Belt-Conveyor-Quick-Fixes.htm | "Unskived splices, fasteners interfering with the cleaners" |
| KB-060 | conveyor belt | manufacturer | https://www.flexco.com/EN/Blogs/HDBCP-HDMBF/Top-10-Belt-Conveyor-Quick-Fixes.htm | "Fasteners that are too large for the smallest pulley" |
| KB-061 | conveyor belt | manufacturer | https://www.flexco.com/EN/Blogs/HDBCP-HDMBF/Top-10-Belt-Conveyor-Quick-Fixes.htm | "Cause: Small pulleys." |
| KB-062 | conveyor belt | manufacturer | https://www.flexco.com/EN/Blogs/HDBCP-HDMBF/Top-10-Belt-Conveyor-Quick-Fixes.htm | "Misalignment of rollers or pulleys, an incorrect splice, and material buildup" |
| KB-063 | conveyor belt | manufacturer | https://www.flexco.com/EN/Blogs/HDBCP-HDMBF/Top-10-Belt-Conveyor-Quick-Fixes.htm | "Cause: Poor skirting, no impact protection." |
| KB-064 | conveyor belt | manufacturer | https://www.flexco.com/EN/Blogs/HDBCP-HDMBF/Top-10-Belt-Conveyor-Quick-Fixes.htm | "Seized rollers cut into belt." |
| KB-065 | conveyor belt | manufacturer | https://blog.martin-eng.com/13-types-of-conveyor-belt-damage | "Cupping occurs when a belt surpasses its specified trough ability" |
| KB-066 | conveyor belt | manufacturer | https://blog.martin-eng.com/13-types-of-conveyor-belt-damage | "Conveyor belts are designed with specific minimum bend radii" |
| KB-067 | conveyor belt | manufacturer | https://blog.martin-eng.com/13-types-of-conveyor-belt-damage | "the belt's carcass can absorb moisture, resulting in what is called ply separation" |
| KB-068 | conveyor belt | manufacturer | https://blog.martin-eng.com/13-types-of-conveyor-belt-damage | "Edge damage occurs when a conveyor belt mistracks" |
| KB-027 | generator | manufacturer | https://support.generac.com/s/article/What-Does-It-Mean-When-My-Generator-Displays-an-Error-Code-Low-Oil-Pressure-Code-1300 | "typically caused by low oil levels due to oil consumption, leaks" |
| KB-069 | generator | manufacturer | https://support.generac.com/s/article/Portable-generator-troubleshooting-quick-reference-guide | "Fuel shut-off is OFF. Turn the fuel shut-off ON." |
| KB-070 | generator | manufacturer | https://support.generac.com/s/article/Portable-generator-troubleshooting-quick-reference-guide | "Circuit Breaker is OPEN Reset Circuit Breaker" |
| KB-071 | generator | manufacturer | https://support.generac.com/s/article/Portable-generator-troubleshooting-quick-reference-guide | "Short circuit in a connected load Disconnect shorted electrical load." |
| KB-072 | generator | manufacturer | https://support.generac.com/s/article/Portable-generator-troubleshooting-quick-reference-guide | "relocate the generator to an open area outside" |
| KB-073 | generator | manufacturer | https://support.generac.com/s/article/Portable-generator-troubleshooting-quick-reference-guide | "The choke is opened too soon" |
| KB-074 | air compressor | manufacturer | https://www.atlascopco.com/en-us/compressors/air-compressor-blog/air-compressor-troubleshooting | "Reset the overload once, if the issue keeps reoccurring consult Atlas Copco" |
| KB-075 | air compressor | manufacturer | https://www.atlascopco.com/en-us/compressors/air-compressor-blog/air-compressor-troubleshooting | "Air consumption exceeds air delivery of compressor" |
| KB-076 | air compressor | manufacturer | https://www.atlascopco.com/en-us/compressors/air-compressor-blog/air-compressor-troubleshooting | "Improve ventilation of compressor room" |
| KB-077 | air compressor | manufacturer | https://www.atlascopco.com/en-us/compressors/air-compressor-blog/air-compressor-troubleshooting | "Check the pressure setpoint and consult Atlas Copco service people" |
| KB-078 | air compressor | manufacturer | https://www.atlascopco.com/en-us/compressors/air-compressor-blog/air-compressor-troubleshooting | "Float valve of condensate trap(s) malfunctioning" |
| KB-079 | air compressor | manufacturer | https://www.atlascopco.com/en-us/compressors/air-compressor-blog/air-compressor-troubleshooting | "Inlet valve stuck in closed position" |
| KB-080 | air compressor | manufacturer | https://www.atlascopco.com/en-us/compressors/air-compressor-blog/air-compressor-troubleshooting | "Dryer capacity exceeded" |
| KB-081 | air compressor | manufacturer | https://us.kaeser.com/compressed-air-resources/compressed-air-tips/getting-the-most-for-your-money/troubleshooting-air-compressors.aspx | "Inspect condensate drains and drain lines; clean or replace defective drain components" |
| KB-082 | air compressor | manufacturer | https://us.kaeser.com/compressed-air-resources/compressed-air-tips/getting-the-most-for-your-money/troubleshooting-air-compressors.aspx | "Drain oil to the correct operating level per manufacturer specification" |
| KB-083 | air compressor | manufacturer | https://us.kaeser.com/compressed-air-resources/compressed-air-tips/getting-the-most-for-your-money/troubleshooting-air-compressors.aspx | "pressure is adequate at the compressor but drops off at the tool or process" |
| KB-084 | air compressor | manufacturer | https://us.kaeser.com/compressed-air-resources/compressed-air-tips/getting-the-most-for-your-money/troubleshooting-air-compressors.aspx | "Check valves and repair or replace as required" |
| KB-085 | air compressor | manufacturer | https://us.kaeser.com/compressed-air-resources/compressed-air-tips/getting-the-most-for-your-money/troubleshooting-air-compressors.aspx | "adjust controls or add receiver capacity as needed to maintain proper run times" |
| KB-086 | air compressor | manufacturer | https://us.kaeser.com/compressed-air-resources/compressed-air-tips/getting-the-most-for-your-money/troubleshooting-air-compressors.aspx | "use an ultrasonic leak detection survey to identify and locate leak points" |
| KB-087 | air compressor | manufacturer | https://us.kaeser.com/compressed-air-resources/compressed-air-tips/getting-the-most-for-your-money/troubleshooting-air-compressors.aspx | "Inspect and re-tension or replace belts; secure all fasteners and guards" |
| KB-088 | boiler | manufacturer | https://www.weil-mclain.com/wp-content/uploads/Users-Manual-CGaS4-CGiS5-EGS7-PEGS7-LGBS2-3-0425.pdf | "Adjust thermostat per manufacturer's instructions." |
| KB-089 | boiler | manufacturer | https://www.weil-mclain.com/wp-content/uploads/Users-Manual-CGaS4-CGiS5-EGS7-PEGS7-LGBS2-3-0425.pdf | "Call qualified service technician to check expansion tank" |
| KB-090 | boiler | manufacturer | https://www.weil-mclain.com/wp-content/uploads/Users-Manual-CGaS4-CGiS5-EGS7-PEGS7-LGBS2-3-0425.pdf | "Do not use petroleum-base stop-leak compounds." |
| KB-091 | boiler | manufacturer | https://www.weil-mclain.com/wp-content/uploads/Users-Manual-CGaS4-CGiS5-EGS7-PEGS7-LGBS2-3-0425.pdf | "Call qualified service technician to de-lime boiler, if necessary." |
| KB-092 | boiler | manufacturer | https://www.weil-mclain.com/wp-content/uploads/Users-Manual-CGaS4-CGiS5-EGS7-PEGS7-LGBS2-3-0425.pdf | "Bleed air from system through air vents in radiators or" |
| KB-093 | boiler | manufacturer | https://www.weil-mclain.com/wp-content/uploads/Users-Manual-CGaS4-CGiS5-EGS7-PEGS7-LGBS2-3-0425.pdf | "Provide outside air for combustion." |
| KB-094 | boiler | manufacturer | https://www.weil-mclain.com/wp-content/uploads/Users-Manual-CGaS4-CGiS5-EGS7-PEGS7-LGBS2-3-0425.pdf | "manual reset lockout, select <Reset Lockout> on" |
| KB-095 | boiler | VENDOR / third-party blog | https://coleindust.com/boiler-troubleshooting/ | "the low-water cutoff (LWCO) will trip, shutting down the burner" |
| KB-096 | boiler | VENDOR / third-party blog | https://coleindust.com/boiler-troubleshooting/ | "A problem with the feedwater system can starve the boiler" |
| KB-097 | boiler | VENDOR / third-party blog | https://coleindust.com/boiler-troubleshooting/ | "The most common cause of high fuel usage is an improper air-to-fuel ratio" |
| KB-098 | boiler | VENDOR / third-party blog | https://coleindust.com/boiler-troubleshooting/ | "If the sensor becomes dirty or simply wears out" |
| KB-099 | boiler | VENDOR / third-party blog | https://coleindust.com/boiler-troubleshooting/ | "A trap that is stuck closed will cause condensate to back up" |
| KB-100 | boiler | VENDOR / third-party blog | https://coleindust.com/boiler-troubleshooting/ | "perform an emergency shutdown immediately and call for professional help" |
| KB-101 | refrigerator/chiller | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003479/ | "Leave 2 inches clearance at the back, top, and sides of the fridge." |
| KB-102 | refrigerator/chiller | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003479/ | "the refrigerator is in Cooling Off Mode, sometimes called Demo mode or Shop mode" |
| KB-103 | refrigerator/chiller | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003479/ | "Blocked vents will prevent air from flowing properly and will result in overcooling." |
| KB-104 | refrigerator/chiller | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003479/ | "If they are dirty, they will fail to create a vacuum seal" |
| KB-105 | refrigerator/chiller | manufacturer | https://www.samsung.com/my/support/home-appliances/8-reasons-why-your-samsung-refrigerator-is-not-cooling/ | "try resetting the circuit breaker for that outlet" |
| KB-106 | refrigerator/chiller | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003479/ | "up to 28 hours for the refrigerator to achieve that temperature" |
| KB-107 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Jog the axis slowly through full travel, watch the load meter, check way lube" |
| KB-108 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Chip-packed way covers, binding ballscrew, dragging brake, overly heavy cuts" |
| KB-109 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Have a qualified electrician measure incoming power and verify taps" |
| KB-110 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Watch the gauge at the machine while it cycles, not just at the compressor" |
| KB-111 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Fill the tank, inspect lines and metering points for flow" |
| KB-112 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Check line voltage first, then the regen resistor and its wiring" |
| KB-113 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Let it cool, then find the mechanical cause of the load" |
| KB-114 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Inspect the encoder cable and look for coolant intrusion" |
| KB-115 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Often triggered by noise, grounding issues, or a genuine board failure" |
| KB-116 | CNC machine | VENDOR / third-party blog | https://www.fabrico.io/blog/haas-alarm-codes-troubleshooting/ | "Release the E-stop, inspect the button and circuit" |
| KB-117 | forklift | VENDOR / third-party blog | https://racklify.com/encyclopedia/counterbalance-forklift-maintenance-checklist-and-safety-practices/ | "inspect mast seals and cylinders for leaks" |
| KB-118 | forklift | VENDOR / third-party blog | https://racklify.com/encyclopedia/counterbalance-forklift-maintenance-checklist-and-safety-practices/ | "Inspect tires, check wheel bearings, and verify engine mounts on IC models." |
| KB-119 | forklift | VENDOR / third-party blog | https://racklify.com/encyclopedia/counterbalance-forklift-maintenance-checklist-and-safety-practices/ | "Inspect brake pads, adjust drums or discs, and check hydraulic brake fluid condition." |
| KB-120 | forklift | VENDOR / third-party blog | https://racklify.com/encyclopedia/counterbalance-forklift-maintenance-checklist-and-safety-practices/ | "battery not holding charge (sulfation, improper charging)" |
| KB-121 | forklift | manufacturer | https://www.toyotaforklift.com/resource-library/blog/safety-support/forklift-safety-brake-inspections | "Driving with the parking brake engaged" |
| KB-122 | UPS | manufacturer | https://www.cyberpowersystems.com/faqs/my-unit-is-beeping-twice-every-15-45-seconds-what-is-happening/ | "Check to ensure that the unit is correctly plugged into the wall outlet" |
| KB-123 | UPS | manufacturer | https://www.cyberpowersystems.com/faqs/my-unit-is-beeping-twice-every-15-45-seconds-what-is-happening/ | "Unplug low priority electronics and plug them into the Surge-only outlets" |
| KB-124 | UPS | manufacturer | https://www.cyberpowersystems.com/faqs/my-unit-is-beeping-twice-every-15-45-seconds-what-is-happening/ | "Turn off the UPS because it’s at about 25% battery" |
| KB-125 | UPS | manufacturer | https://www.vertiv.com/globalassets/products/critical-power/uninterruptible-power-supplies-ups/liebert-pst4-350-500va-user-manual.pdf | "beeps 3 times every 30 seconds until the battery is reconnected or replaced" |
| KB-126 | UPS | manufacturer | https://www.vertiv.com/globalassets/products/critical-power/uninterruptible-power-supplies-ups/liebert-pst4-350-500va-user-manual.pdf | "Reset circuit breaker by pressing the plunger back in" |
| KB-127 | UPS | manufacturer | https://www.vertiv.com/globalassets/products/critical-power/uninterruptible-power-supplies-ups/liebert-pst4-350-500va-user-manual.pdf | "Charge the batteries for 8-hours and retest" |
| KB-128 | UPS | manufacturer | https://www.vertiv.com/globalassets/products/critical-power/uninterruptible-power-supplies-ups/liebert-pst4-350-500va-user-manual.pdf | "Call for a replacement unit" |
| KB-129 | UPS | manufacturer | https://www.vertiv.com/globalassets/products/critical-power/uninterruptible-power-supplies-ups/liebert-pst4-350-500va-user-manual.pdf | "Disconnect the computer cable from the UPS and press the On button" |
| KB-130 | laptop/desktop | manufacturer | https://www.asus.com/us/support/faq/1014276/ | "avoid forced shutdown, and patiently wait for the system to complete memory training" |
| KB-131 | laptop/desktop | manufacturer | https://www.asus.com/us/support/faq/1014276/ | "BIOS file in the root directory of a USB flash drive formatted as FAT32" |
| KB-132 | laptop/desktop | manufacturer | https://www.asus.com/us/support/faq/1014276/ | "Initially, connect the monitor's display output to the integrated graphics card" |
| KB-133 | laptop/desktop | manufacturer | https://www.asus.com/us/support/faq/1012793/ | "This is a normal condition for battery protection" |
| KB-134 | laptop/desktop | manufacturer | https://www.asus.com/us/support/faq/1012793/ | "Maximum lifespan mode: The battery only allows being charged to 60%." |
| KB-135 | laptop/desktop | manufacturer | https://www.asus.com/us/support/faq/1012793/ | "Use the original ASUS adapter and power cord (cable) to avoid compatibility issues." |
| KB-136 | laptop/desktop | manufacturer | https://www.asus.com/za/support/faq/1015064/ | "make sure to turn off the device and disconnect the power cord" |
| KB-137 | laptop/desktop | manufacturer | https://www.asus.com/za/support/faq/1015064/ | "the fan will not spin until the system temperature reaches a certain level" |
| KB-138 | laptop/desktop | manufacturer | https://support.microsoft.com/en-us/surface/surface-won-t-turn-on-or-start-1e181652-3db8-5ca1-9649-7390fafb102a | "Accessories that you’ve connected to your Surface might be preventing it from turning on." |
| KB-139 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "Swap suspect cable with known good cable." |
| KB-140 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "extremely slow performance, intermittent connectivity, and loss of connection" |
| KB-141 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "the problem reoccurs until the root cause is determined" |
| KB-142 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "Both devices must use the same type of GBIC to establish link." |
| KB-143 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "Connections for transmit-to-transmit and receive-to-receive do not work." |
| KB-144 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "A cable can be just good enough to connect at the physical layer" |
| KB-145 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "try and hardcode both sides" |
| KB-146 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "loops can cause serious performance issues that masquerade as port or interface problems" |
| KB-147 | router/network switch | manufacturer | https://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/12027-53.html | "A unidirectional link is a link where traffic goes out one way" |
| KB-148 | router/network switch | government | https://beconnected.esafety.gov.au/pluginfile.php/103683/mod_resource/content/1/index.html | "Wait 30 seconds to 1 minute before plugging it back in." |
| KB-149 | router/network switch | government | https://beconnected.esafety.gov.au/pluginfile.php/103683/mod_resource/content/1/index.html | "the issue is with your Wi-Fi signal" |
| KB-150 | router/network switch | government | https://beconnected.esafety.gov.au/pluginfile.php/103683/mod_resource/content/1/index.html | "Maintenance or technical issues outside your home may cause the internet to drop out." |
| KB-151 | CCTV | manufacturer | https://reolink.com/blog/security-camera-picture-problems-and-solutions/ | "Clean the lens with a soft and clean cloth." |
| KB-152 | CCTV | manufacturer | https://reolink.com/blog/security-camera-picture-problems-and-solutions/ | "Do not point the security camera directly at a source of light" |
| KB-153 | CCTV | manufacturer | https://reolink.com/blog/security-camera-picture-problems-and-solutions/ | "caused by a ground loop problem of the power supply" |
| KB-154 | CCTV | manufacturer | https://reolink.com/blog/security-camera-picture-problems-and-solutions/ | "vertical lines on cctv camera screen that appear to be shaking in place" |
| KB-155 | CCTV | manufacturer | https://reolink.com/blog/security-camera-picture-problems-and-solutions/ | "loose network connections, unstable power supply, interference from nearby electronic devices" |
| KB-156 | CCTV | manufacturer | https://reolink.com/blog/security-camera-picture-problems-and-solutions/ | "Buy a high quality night vision security camera." |
| KB-157 | CCTV | manufacturer | https://reolink.com/blog/security-camera-picture-problems-and-solutions/ | "Make sure you've set the right resolutions for the cameras." |
| KB-158 | water purifier | university | https://naes.unr.edu/publication.aspx?PubID=4789 | "if the treated water smells like rotten eggs and the untreated water does not" |
| KB-159 | water purifier | university | https://naes.unr.edu/publication.aspx?PubID=4789 | "may be in standing water or blocked against the drainpipe" |
| KB-160 | water purifier | university | https://naes.unr.edu/publication.aspx?PubID=4789 | "The higher the air pressure in the bladder, the higher the water pressure" |
| KB-161 | water purifier | university | https://naes.unr.edu/publication.aspx?PubID=4789 | "The filter part of the unit may clog with sand or other particulates" |
| KB-162 | water purifier | university | https://naes.unr.edu/publication.aspx?PubID=4789 | "the carbon filtration cartridge is overloaded and needs replacement" |
| KB-163 | water purifier | manufacturer | https://www.pentair.com/content/dam/extranet/nam/filtration/everpure/commercial/io-guides-manuals/ev3159-33-ez-ro-blend-atm-reva-4-25-22-low-res1.pdf | "will reduce permeate output by 50%" |
| KB-164 | water purifier | manufacturer | https://www.pentair.com/content/dam/extranet/nam/filtration/everpure/commercial/io-guides-manuals/ev3159-33-ez-ro-blend-atm-reva-4-25-22-low-res1.pdf | "Replace membrane cartridge." |
| KB-165 | water purifier | manufacturer | https://www.pentair.com/content/dam/extranet/nam/filtration/everpure/commercial/io-guides-manuals/ev3159-33-ez-ro-blend-atm-reva-4-25-22-low-res1.pdf | "Pump is air locked." |
| KB-166 | water purifier | VENDOR / third-party blog | https://espwaterproducts.com/reverse-osmosis-troubleshooting-guide/ | "Set tank pressure at 5-7 psi when empty" |
| KB-167 | water purifier | VENDOR / third-party blog | https://espwaterproducts.com/reverse-osmosis-troubleshooting-guide/ | "Raise pressure in RO storage tank to 5-7 psi" |
| KB-168 | water purifier | VENDOR / third-party blog | https://espwaterproducts.com/reverse-osmosis-troubleshooting-guide/ | "do not allow water to remain unused more than 5 days" |
| KB-169 | water purifier | VENDOR / third-party blog | https://espwaterproducts.com/reverse-osmosis-troubleshooting-guide/ | "Replace automatic shut off valve" |
| KB-170 | water purifier | VENDOR / third-party blog | https://espwaterproducts.com/reverse-osmosis-troubleshooting-guide/ | "Tiny bubbles - will go away with use" |
| KB-171 | washing machine | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003485/ | "Small loads tend to collect together to one side" |
| KB-172 | washing machine | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003485/ | "The washer should have a solid and firm connection at all four corners." |
| KB-173 | washing machine | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003485/ | "If it's unable to drain, it never moves to the spin step." |
| KB-174 | washing machine | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003485/ | "it creates a siphoning effect which will cause issues with the washer" |
| KB-175 | washing machine | manufacturer | https://www.samsung.com/us/support/troubleshoot/TSG10003485/ | "drain automatically and give an LC or 4C error code" |
| KB-176 | washing machine | VENDOR / third-party blog | https://asurion.com/connect/tech-tips/common-lg-washing-machine-problems/ | "means that your washer can't fill the tub" |
| KB-177 | washing machine | VENDOR / third-party blog | https://asurion.com/connect/tech-tips/common-lg-washing-machine-problems/ | "a drainage issue caused by a clogged drain pump filter or hose" |
| KB-178 | washing machine | VENDOR / third-party blog | https://asurion.com/connect/tech-tips/common-lg-washing-machine-problems/ | "will display an LE if it's overloaded" |
| KB-179 | washing machine | VENDOR / third-party blog | https://asurion.com/connect/tech-tips/common-lg-washing-machine-problems/ | "running a very small load or the load is unbalanced" |
| KB-180 | washing machine | VENDOR / third-party blog | https://asurion.com/connect/tech-tips/common-lg-washing-machine-problems/ | "its legs may be unbalanced" |
| KB-181 | washing machine | VENDOR / third-party blog | https://asurion.com/connect/tech-tips/common-lg-washing-machine-problems/ | "if it has a cracked or torn hose" |
| KB-182 | washing machine | VENDOR / third-party blog | https://asurion.com/connect/tech-tips/common-lg-washing-machine-problems/ | "If there is no humming sound, your washer might need a new drain pump" |
| KB-183 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "could prevent the doors from operating properly, sometimes resulting in an elevator shutdown" |
| KB-184 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "have your electrician check for blown fuses or tripped circuit breakers" |
| KB-185 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "do not attempt to rescue them" |
| KB-186 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "moves your elevator cab to the next available landing in a power failure" |
| KB-187 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "run the car up and down the hoistway for several minutes" |
| KB-188 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "Overloading the unit will cause a fault in the system" |
| KB-189 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "Any binding or dragging indicates a need for alignment or adjustment" |
| KB-190 | elevator | manufacturer | https://www.tkelevator.com/media/usa_canada/downloads_1/eox-elevator-owners-guide.pdf | "If one of the infrared beams is interrupted, the doors will not close" |
| KB-191 | elevator | manufacturer | https://www.schindler.com/content/dam/website/us/docs/safety/schindler-owners-guide.pdf/_jcr_content/renditions/original./schindler-owners-guide.pdf | "return the switch to its normal position" |
| KB-192 | elevator | manufacturer | https://www.schindler.com/content/dam/website/us/docs/safety/schindler-owners-guide.pdf/_jcr_content/renditions/original./schindler-owners-guide.pdf | "When turned off the elevator is not operable." |
| KB-193 | elevator | VENDOR / third-party blog | https://infraspeak.com/en/blog/lift-issues | "Regularly lubricate the moving parts as per the manufacturer's guidelines." |
| KB-194 | elevator | VENDOR / third-party blog | https://infraspeak.com/en/blog/lift-issues | "Clean the door sensors to ensure proper functioning." |
| KB-195 | elevator | VENDOR / third-party blog | https://infraspeak.com/en/blog/lift-issues | "Inspect the leveling sensors for proper alignment and cleanliness." |
| KB-196 | elevator | VENDOR / third-party blog | https://infraspeak.com/en/blog/lift-issues | "Identify the source of the oil leak and repair or replace the damaged components." |
| KB-197 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "Check the inverter's local display or status light." |
| KB-198 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "the inverter stops exporting power for safety" |
| KB-199 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "leave it off and contact a qualified installer" |
| KB-200 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "consult your installer about adding Microinverters or DC Optimizers" |
| KB-201 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "Record the exact error code, inverter model and time of the fault." |
| KB-202 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "verify the breaker between the controller and the battery is switched on" |
| KB-203 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "Dust or bird droppings can cause localized losses." |
| KB-204 | solar inverter | manufacturer | https://www.solaxpower.com/blogs/solar-system-not-working-troubleshooting.html | "Do not touch—contact an installer." |
