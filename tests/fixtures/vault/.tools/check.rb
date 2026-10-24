#!/usr/bin/env ruby
# A made-up check for the test vault. It prints the same format as a real vault check (warnings as "  ! ",
# errors as "  x ", exit 1 on errors) with a few simple rules, so the server's edit flow can be tested.
require "yaml"
require "date"

Dir.chdir(File.expand_path("..", __dir__))
KINDS = %w[topic mechanism event actor question inbox session home positions glossary]
LINK = /\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]/

files = Dir.glob("**/*.md").reject { |f| f.start_with?("Templates/") || f == "CLAUDE.md" }
names = files.map { |f| File.basename(f, ".md") }
errors = []
warnings = []

names.group_by(&:itself).each { |n, list| errors << "duplicate note name '#{n}'" if list.size > 1 }
files.each do |f|
  text = File.read(f)
  head = text[/\A---\n(.*?)\n---\n/m, 1]
  next errors << "#{f}: no frontmatter" unless head
  data = YAML.safe_load(head, permitted_classes: [Date]) || {}
  errors << "#{f}: unknown type #{data["type"].inspect}" unless KINDS.include?(data["type"])
  if data["type"] == "topic"
    errors << "#{f}: topic page must open with a > [!summary] box" unless text =~ /^> \[!summary\]/
  end
  if data["type"] == "event"
    errors << "#{f}: 'from' must be a year number" unless data["from"].is_a?(Integer)
  end
  missing = text.scan(LINK).flatten.map(&:strip).reject { |t| names.include?(t) }
  missing.uniq.each { |t| warnings << "#{f}: links unwritten note '#{t}'" unless f == "Home.md" }
end

puts "#{files.size} notes checked"
puts warnings.empty? ? "Warnings: none" : ["Warnings:", *warnings.map { |w| "  ! #{w}" }]
puts errors.empty? ? "Errors: none" : ["ERRORS:", *errors.map { |e| "  x #{e}" }]
exit(errors.empty? ? 0 : 1)
