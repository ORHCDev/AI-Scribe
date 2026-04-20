# Oscar Database
Connection to the Oscar EMR database is done either by SSHing directly into the database, or to use Selenium to access the web query. The web query can be found on Oscar under in **Administration** &rarr; **Reports** &rarr; **Query By Example** where you can enter SQL queries in query box. 

Using Selenium to access the Oscar database is not ideal, as it slows down the process of querying information, and causes some queries to break. For example, when querying the `eform` table, there is a field that stores the HTML for the eforms and querying with this field will cause interference with how Selenium grabs the query results and nothing will be returned. Ideally, the SSH connection should be used, but in the case where it is difficult to setup, the Selenium connection is an okay option.

All queries that get sent to the Oscar database are all select queries and are of reasonable size (not too large), but if you want to do larger / more complex queries in the future, moving away from using Selenium to query would become necessary.

## Tables
Here is a list of tables inside the Oscar EMR database that are being used:
* `document`: Contains all uploaded documents in the EMR.
* `ctl_document`: Links documents to their patients (used to map document id to patient id).
* `demographic`: Contains patient demographic information (name, address, sex, ...).
* `measurement`: Contains all measurement entries (medication, chief complaint, hpi, ...).
* `eform`: Contains eform templates.
* `eform_data`: Contains filled eforms.
* `appointment`: Contains appointment entries.
* `provider`: Contains provider information.
